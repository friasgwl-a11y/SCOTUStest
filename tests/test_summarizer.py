from app.summarizer import (
    _clean_text,
    _code_to_label,
    _extract_full_syllabus,
    _parse_separate_opinion_entries,
    extract_separate_opinions,
    is_notable,
    split_sentences,
    summarize,
    summarize_extractive,
)

SAMPLE_OPINION_TEXT = """
Cite as: 609 U. S. ____ (2026)
Opinion of the Court
NOTICE: This opinion is subject to formal revision before publication in the
preliminary print of the United States Reports. Readers are requested to
notify the Reporter of Decisions, Supreme Court of the United States,
Washington, D. C. 20543, of any typographical or other formal errors.
SUPREME COURT OF THE UNITED STATES
The Federal Election Campaign Act restricts a political party's coordinated
spending with its own candidates. We must decide whether this restriction
violates the First Amendment. We hold that it does. Restrictions on core
political speech demand exacting scrutiny. The Government failed to show the
restriction is closely drawn to match a sufficiently important interest.
Justice Thomas filed a concurring opinion. Justice Kagan filed a dissenting
opinion, joined by Justice Sotomayor.
2 NATIONAL REPUBLICAN SENATORIAL COMMITTEE v. FEDERAL ELECTION COMM'N
Opinion of the Court
This is a continuation of the analysis on the next page discussing further
details about the coordinated spending limits and their constitutional
infirmities under settled precedent.
"""

SAMPLE_SYLLABUS_TEXT = """
(Slip Opinion) OCTOBER TERM, 2025 1
Syllabus
NOTE: Where it is feasible, a syllabus (headnote) will be released.
SUPREME COURT OF THE UNITED STATES
Syllabus
EXAMPLE v. TEST CASE
CERTIORARI TO THE UNITED STATES COURT OF APPEALS FOR THE NINTH CIRCUIT
No. 24-1. Argued January 1, 2026 - Decided June 1, 2026
Petitioner brought suit alleging the agency exceeded its authority. The
District Court dismissed the complaint and the Court of Appeals affirmed.
Held: The statute's plain text forecloses the agency's reading, and the
judgment below is reversed and remanded for further proceedings. The
ordinary meaning of the operative phrase controls, and nothing in the
statutory structure displaces it. Pp. 4-17.
(a) The text is unambiguous and the canons confirm it. Pp. 4-9.
(b) The agency's contrary policy arguments belong to Congress. Pp. 10-17.
Opinion of the Court
JUSTICE EXAMPLE delivered the opinion of the Court.
This case is about statutory interpretation and the plain meaning rule.
"""


def test_clean_text_strips_boilerplate():
    cleaned = _clean_text(SAMPLE_OPINION_TEXT)
    normalized = " ".join(cleaned.split())  # PDF-derived text keeps line-wrap newlines
    assert "Cite as:" not in cleaned
    assert "NOTICE: This opinion is subject to formal revision" not in cleaned
    assert "Opinion of the Court" not in cleaned
    assert "NATIONAL REPUBLICAN SENATORIAL COMMITTEE v. FEDERAL ELECTION COMM'N" not in cleaned
    assert "Restrictions on core political speech demand exacting scrutiny." in normalized


def test_split_sentences_basic():
    sentences = split_sentences("This is one sentence. This is another sentence here.")
    assert len(sentences) == 2


def test_split_sentences_drops_short_fragments():
    sentences = split_sentences("Ok. This is a real sentence with enough content to keep.")
    assert all(len(s) > 20 for s in sentences)


def test_summarize_extractive_returns_nonempty_and_bounded():
    summary = summarize_extractive(SAMPLE_OPINION_TEXT, max_sentences=2)
    assert summary
    assert len(split_sentences(summary)) <= 2


def test_summarize_extractive_empty_text():
    assert summarize_extractive("") == ""


def test_extract_full_syllabus_finds_segment():
    syllabus = _extract_full_syllabus(SAMPLE_SYLLABUS_TEXT)
    assert syllabus is not None
    # The opinion body starts after the syllabus ends and must be excluded.
    assert "plain meaning rule" not in syllabus
    assert "judgment below is reversed" in syllabus


def test_extract_full_syllabus_starts_at_facts_not_the_caption():
    """The facts should lead, skipping the case caption/docket line -- but
    unlike the old Held-only extraction, the facts themselves must survive."""
    syllabus = _extract_full_syllabus(SAMPLE_SYLLABUS_TEXT)
    assert "CERTIORARI TO THE UNITED STATES COURT OF APPEALS" not in syllabus
    assert "Argued January 1, 2026" not in syllabus
    assert syllabus.lstrip().startswith("Petitioner brought suit")
    assert "Held: The statute's plain text forecloses" in syllabus


def test_extract_full_syllabus_strips_trailing_attribution():
    """The dangling "<Justice>, J.," lead-in to the cut "delivered the
    opinion" sentence shouldn't survive into the reproduced syllabus."""
    syllabus = _extract_full_syllabus(SAMPLE_SYLLABUS_TEXT)
    assert "JUSTICE EXAMPLE" not in syllabus
    assert not syllabus.rstrip().endswith(",")


def test_extract_full_syllabus_returns_none_when_absent():
    assert _extract_full_syllabus("No syllabus heading anywhere in this short order text.") is None


def test_extract_full_syllabus_tolerates_justified_spacing():
    """Some slip opinions (the "preliminary print" bound-volume pages the
    Court's site substitutes in after a term closes) render text with
    per-glyph justification spacing that breaks a plain literal match on
    the end-of-syllabus marker."""
    spaced_text = SAMPLE_SYLLABUS_TEXT.replace(
        "JUSTICE EXAMPLE delivered the opinion of the Court.",
        "J  U S T I C E    E X A M P L E   d e l i v e r e d   t h e   o p i n i o n   o f   t h e   C o u r t .",
    )
    syllabus = _extract_full_syllabus(spaced_text)
    assert syllabus is not None
    assert "judgment below is reversed" in syllabus
    assert "plain meaning rule" not in syllabus


def test_summarize_opinion_returns_full_syllabus_verbatim():
    text, is_syllabus = summarize(SAMPLE_SYLLABUS_TEXT, "Example v. Test Case", "opinion")
    assert is_syllabus is True
    assert "judgment below is reversed" in text
    assert "plain meaning rule" not in text


def test_summarize_falls_back_when_no_syllabus():
    text, is_syllabus = summarize(SAMPLE_OPINION_TEXT, "National Republican v. FEC", "opinion")
    assert is_syllabus is False
    assert text


def test_summarize_order_never_returns_syllabus():
    text, is_syllabus = summarize(SAMPLE_OPINION_TEXT, "Some Order", "order")
    assert is_syllabus is False


SAMPLE_MULTI_OPINION_TEXT = """
1 EXAMPLE v. TEST CASE
Opinion of the Court
JUSTICE EXAMPLE delivered the opinion of the Court.
This case concerns whether the statute applies retroactively. We hold
that it does not, for the reasons given below in a lengthy discussion
that need not be reproduced here in this synthetic fixture text.
The Court of Appeals is affirmed. It is so ordered.

2 EXAMPLE v. TEST CASE

Roberts, J., concurring.

I agree with the Court's judgment and reasoning in full, and write
separately only to note that, as Justice Dissent, J., dissenting observes
elsewhere, the statutory history here is unusually clear, which
reinforces rather than undermines today's holding for the reasons the
Court gives.

3 EXAMPLE v. TEST CASE

Roberts, J., concurring

The concurrence continues on this page with more discussion of the
statutory history and why it supports the Court's reading of the text.

4 EXAMPLE v. TEST CASE

Dissent, J., dissenting.

I would hold that the statute applies retroactively for the reasons
given by the court below, and I respectfully dissent from the Court's
contrary conclusion reached today in this case.
"""


def test_parse_separate_opinion_entries():
    assert _parse_separate_opinion_entries("Thomas (C); Kagan (D)") == [
        ("Thomas", "C"),
        ("Kagan", "D"),
    ]
    assert _parse_separate_opinion_entries("Sotomayor (C/J)") == [("Sotomayor", "C/J")]
    assert _parse_separate_opinion_entries(None) == []
    assert _parse_separate_opinion_entries("") == []


def test_code_to_label():
    assert _code_to_label("C") == "Concurrence"
    assert _code_to_label("D") == "Dissent"
    assert _code_to_label("C/J") == "Concurrence in the judgment"
    assert _code_to_label("D/P") == "Dissent in part"
    assert _code_to_label("C/J/P") == "Concurrence in the judgment in part"
    assert _code_to_label("C/P, C/J") == "Concurrence in part; Concurrence in the judgment"
    assert _code_to_label("C/J/P, D/P") == "Concurrence in the judgment in part; Dissent in part"


def test_extract_separate_opinions_finds_both_in_document_order():
    opinions = extract_separate_opinions(SAMPLE_MULTI_OPINION_TEXT, "Roberts (C); Dissent (D)")
    assert [o["author"] for o in opinions] == ["Roberts", "Dissent"]
    assert opinions[0]["label"] == "Concurrence"
    assert opinions[1]["label"] == "Dissent"


def test_extract_separate_opinions_ignores_inline_citation():
    """A mid-paragraph phrase that happens to contain the literal text
    "Dissent, J., dissenting" -- sharing its line with surrounding prose,
    the same shape a citation like "(Sotomayor, J., dissenting)" takes
    inside another Justice's opinion -- must not be mistaken for that
    Justice's own section heading, which only ever appears alone on its
    line."""
    opinions = extract_separate_opinions(SAMPLE_MULTI_OPINION_TEXT, "Roberts (C); Dissent (D)")
    assert len(opinions) == 2
    roberts = next(o for o in opinions if o["author"] == "Roberts")
    assert "Justice Dissent, J., dissenting observes" in roberts["text"]
    assert "I agree with the Court's judgment" in roberts["text"]


def test_extract_separate_opinions_spans_to_next_opinion_or_end():
    opinions = extract_separate_opinions(SAMPLE_MULTI_OPINION_TEXT, "Roberts (C); Dissent (D)")
    roberts = next(o for o in opinions if o["author"] == "Roberts")
    dissent = next(o for o in opinions if o["author"] == "Dissent")
    assert "concurrence continues on this page" in roberts["text"]
    assert "I would hold that the statute applies retroactively" in dissent["text"]
    assert "contrary conclusion reached today in this case." in dissent["text"]


def test_extract_separate_opinions_empty_when_no_other_field():
    assert extract_separate_opinions(SAMPLE_MULTI_OPINION_TEXT, None) == []
    assert extract_separate_opinions(SAMPLE_MULTI_OPINION_TEXT, "") == []


def test_extract_separate_opinions_skips_footnote_spillover():
    """A long footnote from the end of one opinion sometimes prints onto
    the first page of the next -- a real PDF-layout quirk in the bound
    "preliminary print" pages, not a scraper bug. The reproduced text must
    start at the Justice's own attribution sentence ("Justice X, with whom
    ... dissenting."), not at whatever spillover paragraph shares that
    page with the running header."""
    text = """
1 EXAMPLE v. TEST CASE
Opinion of the Court
JUSTICE EXAMPLE delivered the opinion of the Court.
The judgment is affirmed. It is so ordered.

2 EXAMPLE v. TEST CASE

Dissent, J., dissenting

leftover footnote text continuing a citation from the previous opinion
that happens to spill onto this page before the dissent itself begins,
as sometimes happens with long footnotes near a page break in these
documents.

Justice Dissent, with whom Justice Second joins, dissenting.
I would resolve this case differently for the reasons that follow in
this synthetic fixture text used only to exercise the extraction logic.
"""
    opinions = extract_separate_opinions(text, "Dissent (D)")
    assert len(opinions) == 1
    assert opinions[0]["text"].startswith("Justice Dissent, with whom Justice Second joins, dissenting.")
    assert "leftover footnote text" not in opinions[0]["text"]


def test_extract_separate_opinions_skips_uncocated_entries():
    """A Justice listed in the Granted & Noted List's breakdown but not
    findable in the (possibly page-capped) extracted text is silently
    dropped rather than raising."""
    opinions = extract_separate_opinions(SAMPLE_MULTI_OPINION_TEXT, "Roberts (C); Nobody (D)")
    assert [o["author"] for o in opinions] == ["Roberts"]


def test_is_notable_detects_dissent():
    assert is_notable("Justice Kagan filed a dissenting opinion.") is True
    assert is_notable("The petition for a writ of certiorari is denied.") is False
    assert is_notable("") is False
