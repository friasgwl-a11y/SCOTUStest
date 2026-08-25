"""Summarizes extracted opinion/order text.

Two tiers:
  1. A dependency-free extractive summarizer (word-frequency sentence
     scoring, similar in spirit to Luhn's algorithm) that always works
     offline.
  2. An optional upgrade to Claude (via the Anthropic API) when
     ANTHROPIC_API_KEY is set, for a genuinely abstractive summary. Any
     failure (missing key, network error, rate limit) falls back to (1)
     silently so the dashboard never breaks for lack of an API key.
"""

from __future__ import annotations

import logging
import re

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, MAX_SUMMARY_SENTENCES

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“])")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "that", "this", "it", "is", "was", "are", "were", "be", "been", "as", "at",
    "by", "from", "has", "have", "had", "not", "its", "their", "his", "her",
    "which", "who", "whom", "these", "those", "such", "shall", "may", "must",
    "also", "than", "then", "so", "if", "because", "under", "into", "about",
    "no", "any", "all", "would", "should", "could", "can", "will", "there",
    "here", "when", "where", "while", "we", "us", "our", "you", "your", "they",
    "them", "he", "she", "i", "supra", "id", "see",
}

# Slip opinions/orders repeat "Cite as:" headers and page-footer boilerplate
# on every page; strip these before summarizing so they don't crowd out
# substantive sentences.
_BOILERPLATE_PATTERNS = [
    re.compile(r"^Cite as:.*$", re.MULTILINE),
    re.compile(r"^\d+\s+OCTOBER TERM,?\s+\d{4}.*$", re.MULTILINE),
    re.compile(r"^Opinion of the Court$", re.MULTILINE),
    re.compile(r"^Per Curiam$", re.MULTILINE),
    re.compile(
        r"NOTICE: This opinion is subject to formal revision.*?Reporter of "
        r"Decisions.*?\.",
        re.DOTALL,
    ),
    # Running page headers, e.g. "16 WEST VIRGINIA v. B. P. J." repeated on
    # every page of a slip opinion.
    re.compile(r"^\d{1,4}\s+[A-Z][A-Z.,&'’\-\s]{2,60}?\sv\.\s[A-Z][A-Z.,&'’\-\s]{1,60}$", re.MULTILINE),
    # Repeated separate-opinion headers, e.g. "GORSUCH, J., dissenting" or
    # "THOMAS, J., concurring in part and dissenting in part."
    re.compile(
        r"^[A-Z][A-Z.,\s]{0,40}, (?:C\. )?J\.,\s(?:dissenting|concurring)"
        r"(?:\sin (?:part|the judgment)(?:\sand dissenting in part)?)?\.?$",
        re.MULTILINE,
    ),
    # Case-caption block repeated at the start of each separate opinion in a
    # combined PDF (per curiam + dissents), e.g. "SUPREME COURT OF THE
    # UNITED STATES / ___ / No. 26A124 / ___ / ... / [August 24, 2026]".
    re.compile(r"SUPREME COURT OF THE UNITED STATES.{0,800}?\[[A-Za-z]+ \d{1,2}, \d{4}\]", re.DOTALL),
    # "Syllabus" repeats as a running page header throughout the syllabus
    # section (every page), same as "Opinion of the Court" does in the body.
    re.compile(r"^Syllabus$", re.MULTILINE),
]


def _normalize_lines(text: str) -> str:
    """Strips per-line padding and leading page numbers.

    Different PDF text extractors lay the same page out differently --
    pypdf emits trailing spaces and prefixes the running header with the
    page number ("1  Cite as: 609 U. S. ____ (2026) "), where pdfplumber
    does not. The boilerplate patterns below are line-anchored, so
    normalizing first keeps them working regardless of which extractor
    produced the text.
    """
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Drop a bare page number preceding a running header.
        line = re.sub(r"^\d{1,4}\s+(?=Cite as:|OCTOBER TERM)", "", line)
        lines.append(line)
    return "\n".join(lines)


def _clean_text(text: str) -> str:
    cleaned = _normalize_lines(text)
    for pattern in _BOILERPLATE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    # Rejoin words split by a line-wrap hyphen, e.g. "regard-\ning" -> "regarding".
    cleaned = re.sub(r"(\w)-\s+(\w)", r"\1\2", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)
    return cleaned.strip()


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    sentences = _SENTENCE_SPLIT_RE.split(normalized)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def summarize_extractive(text: str, max_sentences: int = MAX_SUMMARY_SENTENCES) -> str:
    cleaned = _clean_text(text)
    sentences = split_sentences(cleaned)
    if not sentences:
        return ""
    if len(sentences) <= max_sentences:
        return " ".join(sentences)

    freq: dict[str, int] = {}
    for sentence in sentences:
        for word in _WORD_RE.findall(sentence.lower()):
            if word in _STOPWORDS or len(word) < 3:
                continue
            freq[word] = freq.get(word, 0) + 1

    if not freq:
        return " ".join(sentences[:max_sentences])

    max_freq = max(freq.values())
    for word in freq:
        freq[word] /= max_freq

    scored = []
    for idx, sentence in enumerate(sentences):
        words = _WORD_RE.findall(sentence.lower())
        if not words:
            continue
        score = sum(freq.get(w, 0) for w in words) / len(words)
        # Mild bias toward earlier sentences (topic sentences, holdings)
        # and away from very short/long outliers.
        position_bonus = 1.15 if idx < 3 else 1.0
        scored.append((score * position_bonus, idx, sentence))

    top = sorted(scored, key=lambda x: x[0], reverse=True)[:max_sentences]
    top_in_order = [s for _, _, s in sorted(top, key=lambda x: x[1])]
    return " ".join(top_in_order)


def summarize_with_anthropic(text: str, case_label: str, doc_kind: str) -> str | None:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed; skipping AI summary")
        return None

    truncated = text[:60000]  # keep well within context; slip opinions rarely exceed this
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are summarizing a U.S. Supreme Court {doc_kind} "
                        f"for a legal-tracking dashboard: {case_label}.\n\n"
                        "In 3-5 sentences, state the holding/disposition, the "
                        "key legal question, and any notable separate "
                        "opinions (concurrence/dissent) or vote breakdown "
                        "mentioned in the text. Be precise and neutral; do "
                        "not editorialize.\n\n"
                        f"TEXT:\n{truncated}"
                    ),
                }
            ],
        )
        parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        return "\n".join(parts).strip() or None
    except Exception as exc:
        logger.warning("Anthropic summarization failed for %s: %s", case_label, exc)
        return None


def _loose(phrase: str) -> str:
    """Matches `phrase` tolerating stray whitespace between any of its
    letters (but requiring real whitespace between its words). Some slip
    opinions -- especially the "preliminary print" bound-volume pages the
    Court's site substitutes in once a term's slip opinions are folded
    into a printed volume -- apply per-glyph justification that pypdf
    surfaces as extra whitespace mid-word (e.g. "delivered the opini on
    of the Cour t"), which a plain literal match misses."""
    words = phrase.split(" ")
    return r"\s+".join(r"\s*".join(re.escape(ch) for ch in w) for w in words)


_SYLLABUS_START_RE = re.compile(r"\bSyllabus\b")
# The case caption/docket line ("CERTIORARI TO THE ... CIRCUIT / No. 24-297.
# Argued April 22, 2025—Decided June 27, 2025") separates the "Syllabus"
# heading from the facts paragraph that actually starts the substance.
# Starting after it skips the caption without losing the facts, unlike the
# old approach of starting at "Held:" (which dropped the facts entirely).
_DOCKET_CAPTION_RE = re.compile(r"No\.\s+\S[^\n]*(?:Argued|Submitted|Decided)[^\n]*")
# What follows a syllabus is always some variant of "<Justice> delivered
# the opinion/judgment of the Court" or "PER CURIAM" -- but the surname is
# unpredictable (any sitting Justice) and, in the bound-volume pages,
# often rendered without the "JUSTICE" prefix at all, so match on the
# stable trailing phrase rather than the name.
_SYLLABUS_END_RE = re.compile(
    "|".join(
        _loose(p)
        for p in [
            "delivered the opinion of the Court",
            "delivered the judgment of the Court",
            "announced the judgment of the Court",
            "delivered a per curiam opinion",
            "PER CURIAM",
        ]
    )
)


# The line right before the end marker is always the Justice attribution
# that leads into the cut "delivered the opinion..." sentence -- either
# "JUSTICE <NAME>" (standard slip opinions) or "<surname>, J.," / ", C. J.,"
# (the bound "preliminary print" pages' style). Strip that dangling
# fragment from the end.
_TRAILING_ATTRIBUTION_RE = re.compile(
    r"(?:JUSTICE\s+[A-Z.'’\-]+|[A-Z][A-Za-z.'’\-]{1,30}\s*,\s*(?:C\.\s*)?J\s*\.\s*,?)\s*$"
)


def _extract_full_syllabus(text: str) -> str | None:
    """Slip opinions with a syllabus include the Reporter of Decisions' own
    headnote -- an authoritative, already-condensed statement of the facts,
    question, and holding. Returns the full syllabus (facts through Held),
    boilerplate-cleaned, or None if no syllabus section is found (e.g.
    orders, short per curiam opinions)."""
    start = _SYLLABUS_START_RE.search(text)
    if not start:
        return None
    end = _SYLLABUS_END_RE.search(text, start.end())
    stop = end.start() if end else min(len(text), start.end() + 20000)

    docket = _DOCKET_CAPTION_RE.search(text, start.end(), stop)
    begin = docket.end() if docket else start.end()

    segment = _clean_text(text[begin:stop])
    segment = _TRAILING_ATTRIBUTION_RE.sub("", segment).rstrip()
    return segment if len(segment) > 200 else None


def summarize(text: str, case_label: str, doc_kind: str = "opinion") -> tuple[str, bool]:
    """Returns (text, is_verbatim_syllabus).

    Opinions with a syllabus get it reproduced verbatim: it's already the
    Court's own authoritative summary, so re-summarizing it risks losing
    accuracy for no benefit. Generated summarization (Claude, or the
    offline extractive fallback) only runs when there's no syllabus to
    show -- most orders, and the rare short per curiam opinion.
    """
    if not text or not text.strip():
        return "", False
    if doc_kind == "opinion":
        syllabus = _extract_full_syllabus(text)
        if syllabus:
            return syllabus, True
    ai_summary = summarize_with_anthropic(text, case_label, doc_kind)
    if ai_summary:
        return ai_summary, False
    return summarize_extractive(text), False


_NOTABLE_RE = re.compile(
    r"\b(dissent|dissenting|concur|concurring|statement of|would grant|"
    r"cert(?:iorari)?\.? granted|stay granted|stay denied|recuse)\b",
    re.IGNORECASE,
)


def is_notable(text: str) -> bool:
    return bool(text) and bool(_NOTABLE_RE.search(text))
