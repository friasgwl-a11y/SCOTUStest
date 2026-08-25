"""Scrapes opinions and orders listing pages from supremecourt.gov.

The Court's website has no JSON/RSS feed for these lists, so we parse the
HTML tables/lists directly. Structure was verified against live pages on
2026-08-25:

  Opinions: https://www.supremecourt.gov/opinions/slipopinion/{term}
    One or more <table class="table table-bordered"> elements (a visible
    table plus a collapsed "More" table further down the page), each with
    header row <th>R-</th><th>Date</th><th>Docket</th><th>Name</th><th>J.</th>
    <th>Citation</th> followed by data rows. The case-name cell's anchor
    carries a `title` attribute containing the Court's own one-line
    holding/syllabus summary, and may be followed by "Revisions:" links to
    corrected slip opinions.

  Orders: https://www.supremecourt.gov/orders/ordersofthecourt/{term}
    Repeated <div style="display:block"> blocks, each containing a date
    span ("MM/DD/YY") and a link span whose <a> text is "Order List" or
    "Miscellaneous Order" and whose href points at the order PDF.

Both pages are ASP.NET Web Forms pages rendered server-side, so a plain GET
with a descriptive User-Agent is sufficient; no JS execution is needed.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.config import BASE_URL, REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")


@dataclass
class ScrapedOpinion:
    term: str
    rank: str | None
    date: dt.date | None
    docket: str | None
    case_name: str
    justice: str | None
    citation: str | None
    pdf_url: str
    holding: str | None
    is_revision: bool = False


@dataclass
class ScrapedOrder:
    term: str
    date: dt.date | None
    order_type: str
    pdf_url: str


@dataclass
class FetchResult:
    opinions: list[ScrapedOpinion] = field(default_factory=list)
    orders: list[ScrapedOrder] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_date(text: str) -> dt.date | None:
    match = _DATE_RE.search(text or "")
    if not match:
        return None
    month, day, year = match.groups()
    year_int = int(year)
    if year_int < 100:
        year_int += 2000 if year_int < 70 else 1900
    try:
        return dt.date(year_int, int(month), int(day))
    except ValueError:
        return None


def _get(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_opinions_page(term: str) -> tuple[list[ScrapedOpinion], list[str]]:
    url = f"{BASE_URL}/opinions/slipopinion/{term}"
    errors: list[str] = []
    try:
        html = _get(url)
    except requests.RequestException as exc:
        return [], [f"opinions term {term}: {exc}"]

    soup = BeautifulSoup(html, "html.parser")
    opinions: list[ScrapedOpinion] = []

    for table in soup.select("table.table-bordered"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue  # header row or malformed row

            rank = cells[0].get_text(strip=True) or None
            date = _parse_date(cells[1].get_text(strip=True))
            docket = cells[2].get_text(strip=True) or None
            justice = cells[4].get_text(strip=True) or None
            citation = cells[5].get_text(strip=True) or None

            anchors = cells[3].find_all("a")
            if not anchors:
                continue
            main_anchor = anchors[0]
            href = main_anchor.get("href")
            if not href:
                continue
            case_name = main_anchor.get_text(strip=True)
            holding = main_anchor.get("title") or None
            pdf_url = urljoin(BASE_URL, href)

            opinions.append(
                ScrapedOpinion(
                    term=term,
                    rank=rank,
                    date=date,
                    docket=docket,
                    case_name=case_name,
                    justice=justice,
                    citation=citation,
                    pdf_url=pdf_url,
                    holding=holding,
                    is_revision=False,
                )
            )

            # Any additional anchors in the cell are "Revisions" links to
            # corrected slip opinions for the same case.
            for rev_anchor in anchors[1:]:
                rev_href = rev_anchor.get("href")
                if not rev_href:
                    continue
                opinions.append(
                    ScrapedOpinion(
                        term=term,
                        rank=rank,
                        date=_parse_date(rev_anchor.get_text(strip=True)) or date,
                        docket=docket,
                        case_name=f"{case_name} (revised)",
                        justice=justice,
                        citation=citation,
                        pdf_url=urljoin(BASE_URL, rev_href),
                        holding=holding,
                        is_revision=True,
                    )
                )

    return opinions, errors


def fetch_orders_page(term: str) -> tuple[list[ScrapedOrder], list[str]]:
    url = f"{BASE_URL}/orders/ordersofthecourt/{term}"
    try:
        html = _get(url)
    except requests.RequestException as exc:
        return [], [f"orders term {term}: {exc}"]

    soup = BeautifulSoup(html, "html.parser")
    orders: list[ScrapedOrder] = []

    for block in soup.find_all("div", style=re.compile(r"display:\s*block")):
        spans = block.find_all("span", recursive=False)
        if len(spans) < 2:
            continue
        date = _parse_date(spans[0].get_text(strip=True))
        anchor = spans[1].find("a")
        if not anchor or not anchor.get("href"):
            continue
        order_type = anchor.get_text(strip=True) or "Order"
        pdf_url = urljoin(BASE_URL, anchor["href"])
        orders.append(ScrapedOrder(term=term, date=date, order_type=order_type, pdf_url=pdf_url))

    return orders, []


def fetch_all(terms: list[str]) -> FetchResult:
    result = FetchResult()
    for i, term in enumerate(terms):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        opinions, errs = fetch_opinions_page(term)
        result.opinions.extend(opinions)
        result.errors.extend(errs)

        time.sleep(REQUEST_DELAY_SECONDS)
        orders, errs = fetch_orders_page(term)
        result.orders.extend(orders)
        result.errors.extend(errs)

    return result
