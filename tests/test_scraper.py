import datetime as dt
from pathlib import Path

import pytest

from app import scraper

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def fake_http(monkeypatch):
    def fake_get(url: str) -> str:
        if "opinions" in url:
            return (FIXTURES / "opinions_sample.html").read_text(encoding="utf-8", errors="ignore")
        return (FIXTURES / "orders_sample.html").read_text(encoding="utf-8", errors="ignore")

    monkeypatch.setattr(scraper, "_get", fake_get)
    monkeypatch.setattr(scraper, "REQUEST_DELAY_SECONDS", 0)


def test_fetch_opinions_page_parses_all_rows():
    opinions, errors = scraper.fetch_opinions_page("25")
    assert errors == []
    # 69 primary entries (rank 1-69) plus 7 "Revisions" links found in the fixture.
    assert len(opinions) == 76
    assert sum(1 for o in opinions if o.is_revision) == 7


def test_fetch_opinions_page_extracts_expected_fields():
    opinions, _ = scraper.fetch_opinions_page("25")
    first = opinions[0]
    assert first.case_name == "Trump v. California"
    assert first.docket == "26A124"
    assert first.date == dt.date(2026, 8, 24)
    assert first.justice == "PC"
    assert first.pdf_url == "https://www.supremecourt.gov/opinions/25pdf/26a124_hgci.pdf"
    assert first.holding and "stay" in first.holding.lower()
    assert first.is_revision is False


def test_fetch_opinions_page_skips_header_rows():
    opinions, _ = scraper.fetch_opinions_page("25")
    assert all(o.case_name for o in opinions)
    assert all(o.pdf_url.startswith("https://www.supremecourt.gov/") for o in opinions)


def test_fetch_orders_page_parses_all_entries():
    orders, errors = scraper.fetch_orders_page("25")
    assert errors == []
    assert len(orders) == 109


def test_fetch_orders_page_extracts_expected_fields():
    orders, _ = scraper.fetch_orders_page("25")
    first = orders[0]
    assert first.date == dt.date(2026, 8, 21)
    assert first.order_type == "Miscellaneous Order"
    assert first.pdf_url == "https://www.supremecourt.gov/orders/courtorders/082126zr_5h26.pdf"


def test_fetch_orders_page_order_type_values_are_nonempty():
    # The orders page mostly lists "Order List" / "Miscellaneous Order" but
    # also occasionally rule-amendment orders (e.g. "Rules of Evidence"), so
    # we only assert every entry got a real label, not a fixed vocabulary.
    orders, _ = scraper.fetch_orders_page("25")
    assert all(o.order_type.strip() for o in orders)
    assert {"Order List", "Miscellaneous Order"} <= {o.order_type for o in orders}


def test_parse_date_handles_two_digit_year():
    assert scraper._parse_date("8/24/26") == dt.date(2026, 8, 24)
    assert scraper._parse_date("not a date") is None


def test_fetch_all_combines_terms():
    result = scraper.fetch_all(["25"])
    assert len(result.opinions) == 76
    assert len(result.orders) == 109
    assert result.errors == []
