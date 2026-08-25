from app.summarizer import (
    _clean_text,
    _extract_syllabus,
    is_notable,
    split_sentences,
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
No. 24-1. Argued January 1, 2026 - Decided June 1, 2026
The Court holds that the statute means what it says. Held: the judgment
below is reversed.
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


def test_extract_syllabus_finds_segment():
    syllabus = _extract_syllabus(SAMPLE_SYLLABUS_TEXT)
    assert syllabus is not None
    assert "statutory interpretation" not in syllabus  # that's in the opinion body, after Syllabus ends
    assert "judgment" in syllabus.lower() or "statute" in syllabus.lower()


def test_extract_syllabus_returns_none_when_absent():
    assert _extract_syllabus("No syllabus heading anywhere in this short order text.") is None


def test_is_notable_detects_dissent():
    assert is_notable("Justice Kagan filed a dissenting opinion.") is True
    assert is_notable("The petition for a writ of certiorari is denied.") is False
    assert is_notable("") is False
