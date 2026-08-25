from pathlib import Path

from app.qp_scraper import normalize_docket_for_qp, parse_qp_pdf, qp_url_for_docket

PDFS = Path(__file__).parent / "fixtures" / "pdfs"


def test_normalize_docket_zero_pads_cert_dockets():
    assert normalize_docket_for_qp("24-43") == "24-00043"
    assert normalize_docket_for_qp("23-1197") == "23-01197"


def test_normalize_docket_strips_consolidated_and_flag_suffixes():
    assert normalize_docket_for_qp("24-1021)1*") == "24-01021"
    assert normalize_docket_for_qp("23-1209*") == "23-01209"
    assert normalize_docket_for_qp("24-171#") == "24-00171"


def test_normalize_docket_leaves_application_dockets_unpadded():
    assert normalize_docket_for_qp("25A312") == "25A312"


def test_normalize_docket_unknown_format_returns_none():
    assert normalize_docket_for_qp("weird-format") is None


def test_qp_url_for_docket():
    assert qp_url_for_docket("24-43") == "https://www.supremecourt.gov/qp/24-00043qp.pdf"
    assert qp_url_for_docket("25A312") == "https://www.supremecourt.gov/qp/25A312qp.pdf"
    assert qp_url_for_docket("not-a-docket") is None


def test_parse_qp_pdf_single_question():
    record = parse_qp_pdf((PDFS / "qp_landor_sample.pdf").read_bytes())
    assert record.case_name == "LANDOR V. LA DEPT. OF CORRECTIONS"
    assert record.decision_below == "82 F.4th 337"
    assert record.lower_court_case_number == "22-30686"
    assert record.status_line == "CERT. GRANTED 6/23/2025"
    assert "RLUIPA" in record.question_presented
    # The status stamp must not leak into the question text.
    assert "CERT. GRANTED" not in record.question_presented


def test_parse_qp_pdf_multiple_questions():
    record = parse_qp_pdf((PDFS / "qp_westvirginia_sample.pdf").read_bytes())
    assert record.case_name == "WEST VIRGINIA V. B.P.J."
    assert record.status_line == "CERT. GRANTED 7/3/2025"
    assert "Title IX" in record.question_presented
    assert "Equal Protection Clause" in record.question_presented


def test_parse_qp_pdf_application_with_no_real_question():
    record = parse_qp_pdf((PDFS / "qp_trumpvcook_sample.pdf").read_bytes())
    assert record.case_name == "TRUMP V. COOK"
    assert record.status_line == "JURISDICTION NOTED 10/1/2025"
    assert "DEFERRED PENDING ORAL ARGUMENT" in record.question_presented
