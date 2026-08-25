import datetime as dt
from pathlib import Path

from app.term_scraper import (
    fetch_term_links,
    parse_granted_noted_list,
    parse_monthly_argument_calendar,
)

FIXTURES = Path(__file__).parent / "fixtures"
PDFS = FIXTURES / "pdfs"


def test_fetch_term_links_finds_current_term():
    html = (FIXTURES / "calendarsandlists_sample.html").read_text(encoding="utf-8", errors="ignore")
    links = fetch_term_links(html)
    current = [t for t in links if t.is_current]
    assert len(current) == 1
    assert current[0].term == "25"
    assert current[0].label == "October Term 2025"


def test_fetch_term_links_collects_argument_calendar_pdfs():
    html = (FIXTURES / "calendarsandlists_sample.html").read_text(encoding="utf-8", errors="ignore")
    links = fetch_term_links(html)
    by_term = {t.term: t for t in links}
    assert len(by_term["25"].argument_calendar_pdfs) == 7
    assert all(url.endswith(".pdf") for url in by_term["25"].argument_calendar_pdfs)


def test_parse_granted_noted_list_counts_all_entries():
    pdf_bytes = (PDFS / "granted25_sample.pdf").read_bytes()
    cases = parse_granted_noted_list(pdf_bytes)
    assert len(cases) == 64
    assert len({c.docket for c in cases}) == 64  # no duplicates


def test_parse_granted_noted_list_extracts_fields():
    pdf_bytes = (PDFS / "granted25_sample.pdf").read_bytes()
    cases = {c.docket: c for c in parse_granted_noted_list(pdf_bytes)}

    landor = cases["23-1197"]
    assert landor.case_name == "LANDOR V. LOUISIANA DEPT. OF CORRECTIONS AND PUBLIC SAFETY"
    assert landor.court == "USCA-5"
    assert landor.granted_date == dt.date(2025, 6, 23)
    assert landor.argument_date == dt.date(2025, 11, 10)
    assert landor.decided_date == dt.date(2026, 6, 23)
    assert landor.author == "J. Gorsuch"
    assert landor.other == "Jackson (D)"
    assert landor.result == "AFFIRMED"


def test_parse_granted_noted_list_result_field_not_polluted_by_page_boilerplate():
    # Regression: an entry landing near a page break used to have the next
    # page's repeated header ("SUPREME COURT OF THE UNITED STATES...")
    # appended to its Result field.
    pdf_bytes = (PDFS / "granted25_sample.pdf").read_bytes()
    cases = {c.docket: c for c in parse_granted_noted_list(pdf_bytes)}
    for docket in ("24-345", "25A312"):
        assert "SUPREME COURT" not in cases[docket].result
        assert "GRANTED" not in cases[docket].result.upper() or docket == "25A312"


def test_parse_granted_noted_list_consolidated_cases_share_fields():
    pdf_bytes = (PDFS / "granted25_sample.pdf").read_bytes()
    cases = {c.docket: c for c in parse_granted_noted_list(pdf_bytes)}
    little = cases["24-38"]
    west_virginia = cases["24-43"]
    assert little.case_name == "LITTLE V. HECOX"
    assert west_virginia.case_name == "WEST VIRGINIA V. B. P. J."
    # Consolidated cases share the same argument/decision dates.
    assert little.argument_date == west_virginia.argument_date
    assert little.decided_date == west_virginia.decided_date


def test_parse_monthly_argument_calendar_dates_and_cases():
    pdf_bytes = (PDFS / "argcal_october2026_sample.pdf").read_bytes()
    days = parse_monthly_argument_calendar(pdf_bytes)
    by_date = {d.date: d for d in days}

    assert by_date[dt.date(2026, 10, 5)].cases == [
        ("25-170", "SUNCOR ENERGY (U.S.A.) INC. V. COMM ISSIONERS OF BOULDER COUNTY"),
        ("25-735", "JOHNSON V. UNITED STATES CONGRESS"),
    ]
    assert by_date[dt.date(2026, 10, 13)].cases == [
        ("25-5343", "BEAIRD V. UNITED STATES"),
        ("25-886", "GENALO V. BLACK"),
    ]


def test_parse_monthly_argument_calendar_holiday_has_no_cases():
    pdf_bytes = (PDFS / "argcal_october2026_sample.pdf").read_bytes()
    days = parse_monthly_argument_calendar(pdf_bytes)
    holiday = next(d for d in days if d.date == dt.date(2026, 10, 12))
    assert holiday.is_holiday
    assert holiday.cases == []


def test_parse_monthly_argument_calendar_sorted_chronologically():
    pdf_bytes = (PDFS / "argcal_october2026_sample.pdf").read_bytes()
    days = parse_monthly_argument_calendar(pdf_bytes)
    dates = [d.date for d in days]
    assert dates == sorted(dates)


def test_parse_monthly_argument_calendar_no_footer_bleed():
    # Regression: "Court convenes at 10 a.m." plus the PDF's print-date
    # stamp used to get appended to the last case name in a column.
    pdf_bytes = (PDFS / "argcal_october2026_sample.pdf").read_bytes()
    days = parse_monthly_argument_calendar(pdf_bytes)
    for day in days:
        for _docket, case_name in day.cases:
            assert "Court convenes" not in case_name
            assert "2026" not in case_name  # the print-date stamp's year
