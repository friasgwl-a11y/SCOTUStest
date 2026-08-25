from app.dockets import normalize_docket


def test_normalize_docket_passthrough():
    assert normalize_docket("24-43") == "24-43"
    assert normalize_docket("23-1197") == "23-1197"
    assert normalize_docket("25A312") == "25A312"


def test_normalize_docket_strips_list_flags():
    assert normalize_docket("24-171#") == "24-171"
    assert normalize_docket("23-1209*") == "23-1209"
    assert normalize_docket("24-482*") == "24-482"


def test_normalize_docket_strips_consolidated_markers():
    assert normalize_docket("24-1021)1*") == "24-1021"
    assert normalize_docket("24-1287)1") == "24-1287"
    assert normalize_docket("24-1113)2") == "24-1113"
    assert normalize_docket("25-1083)1") == "25-1083"


def test_normalize_docket_strips_trailing_paren_without_number():
    # PDF line-wrap leftover, observed on the OT2025 Granted & Noted List
    # for dockets like 24-820) / 24-109).
    assert normalize_docket("24-820)") == "24-820"
    assert normalize_docket("24-109)") == "24-109"
    assert normalize_docket("24-110)") == "24-110"


def test_normalize_docket_empty_and_whitespace():
    assert normalize_docket(None) == ""
    assert normalize_docket("") == ""
    assert normalize_docket("  24-43  ") == "24-43"
