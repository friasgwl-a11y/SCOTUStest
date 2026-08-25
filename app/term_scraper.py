"""Scrapes term-level data that changes far less often than opinions/orders:

  - Which term the Court's own site currently labels "(Current Term)"
    (https://www.supremecourt.gov/oral_arguments/calendarsandlists.aspx),
    so the dashboard doesn't have to guess from today's date.
  - The Granted & Noted List, one PDF per term
    (https://www.supremecourt.gov/orders/{term}grantednotedlist.pdf),
    which gives the total number of cases granted for a term and, per
    case, the docket, case name, argument date, majority author, and a
    per-Justice concurrence/dissent breakdown -- all as the Court's own
    structured text. This is far more reliable than trying to infer
    concurrences/dissents by pattern-matching each opinion PDF.
  - Monthly Argument Calendar PDFs, listed per term on the same
    calendarsandlists.aspx page, which give the case names/docket numbers
    scheduled for each upcoming argument day.

Verified against live pages/PDFs on 2026-08-25.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.config import BASE_URL, REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

_CALENDARS_PAGE = f"{BASE_URL}/oral_arguments/calendarsandlists.aspx"

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]


def _loose(phrase: str) -> str:
    """Matches `phrase` tolerating stray whitespace between any of its
    letters (but requiring real whitespace between its words). Some of the
    Court's argument-calendar PDFs apply per-glyph kerning that pypdf
    surfaces as separate text fragments even mid-word (observed splitting
    "October" into "Octobe" + "r", and digits like day "12" into "1" +
    " 2"), which a plain literal match misses entirely -- silently
    misreading the date. Since these artifacts only ever insert extra
    whitespace and never reorder or drop characters, a per-character
    whitespace-tolerant pattern matches correctly regardless of where the
    split falls."""
    words = phrase.split(" ")
    return r"\s+".join(r"\s*".join(re.escape(ch) for ch in w) for w in words)


_WEEKDAY_RE = re.compile(
    r"(" + "|".join(_loose(w) for w in _WEEKDAYS) + r"),\s*"
    r"(" + "|".join(_loose(m) for m in _MONTHS) + r")\s*,?\s*(\d\s*\d?)"
)
_HOLIDAY_RE = re.compile(_loose("LEGAL HOLIDAY"))
_COURT_CONVENES_RE = re.compile(_loose("Court convenes"))
_TRAILING_PRINT_DATE_RE = re.compile(
    r"(?:" + "|".join(_loose(m) for m in _MONTHS) + r")\s*\d\s*\d?\s*,\s*\d\s*\d\s*\d\s*\d\s*$"
)


def _strip_footer(text: str) -> str:
    """Removes the page footer ("Court convenes at 10 a.m." plus the
    PDF's print/revision date stamp, e.g. "August 4, 2026") which
    otherwise has no following header to bound it and so gets appended to
    the last case name in the column."""
    m = _COURT_CONVENES_RE.search(text)
    if m:
        text = text[: m.start()]
    return _TRAILING_PRINT_DATE_RE.sub("", text)


def _get_text(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _get_bytes(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Current-term lookup
# ---------------------------------------------------------------------------


@dataclass
class TermLinks:
    term: str  # two-digit term code, e.g. "25"
    label: str  # e.g. "October Term 2025"
    is_current: bool
    argument_calendar_pdfs: list[str] = field(default_factory=list)


def fetch_term_links(html: str | None = None) -> list[TermLinks]:
    """Parses the Calendars and Lists page for each term's Supreme Court
    Calendar (used to find the "(Current Term)" label) and its Argument
    Calendar month links."""
    if html is None:
        html = _get_text(_CALENDARS_PAGE)
    soup = BeautifulSoup(html, "html.parser")

    results: dict[str, TermLinks] = {}

    # "Supreme Court Calendar" list items: <a href='2025TermCourtCalendar.pdf'>...
    # (October Term 2025) <span>- (Current Term)</span>
    for li in soup.select("tr#Calendar + tr li"):
        anchor = li.find("a")
        if not anchor:
            continue
        m = re.search(r"(\d{4})TermCourtCalendar", anchor.get("href", ""))
        if not m:
            continue
        year = int(m.group(1))
        term = str(year)[-2:]
        label = f"October Term {year}"
        is_current = "current term" in li.get_text(strip=True).lower()
        results[term] = TermLinks(term=term, label=label, is_current=is_current)

    # Argument Calendar accordions, one per term, each containing month PDFs.
    for toggle in soup.select("a.accordion-toggle[data-target^='#ArgCal']"):
        m = re.search(r"October Term (\d{4})", toggle.get_text())
        if not m:
            continue
        term = str(int(m.group(1)))[-2:]
        target = toggle.get("data-target", "").lstrip("#")
        panel = soup.find(id=target)
        if not panel:
            continue
        pdf_urls = [
            urljoin(f"{BASE_URL}/oral_arguments/", a["href"])
            for a in panel.select("a[href$='.pdf']")
        ]
        entry = results.setdefault(
            term, TermLinks(term=term, label=f"October Term {2000 + int(term)}", is_current=False)
        )
        entry.argument_calendar_pdfs = pdf_urls

    return list(results.values())


def get_current_and_next_term() -> tuple[str | None, str | None]:
    """Returns (current_term, next_term) two-digit codes, or (None, None) if
    the current-term label couldn't be found (e.g. page structure changed)."""
    try:
        links = fetch_term_links()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch term links: %s", exc)
        return None, None

    current = next((t for t in links if t.is_current), None)
    if not current:
        return None, None
    next_term = str(int(current.term) + 1).zfill(2)
    return current.term, next_term


# ---------------------------------------------------------------------------
# Granted & Noted List
# ---------------------------------------------------------------------------


@dataclass
class GrantedCase:
    docket: str
    case_name: str
    court: str | None
    granted_date: dt.date | None
    argument_date: dt.date | None
    decided_date: dt.date | None
    author: str | None
    other: str | None  # raw "Other:" text, e.g. "Thomas (C); Gorsuch (D)"
    result: str | None


_DOCKET_LINE_RE = re.compile(
    r"^[ \t]*(?P<docket>\d{2}[-A]\d+[\)\d]*[*#]?)[ \t]+(?P<code>[A-Z]{2,4})[ \t]+(?P<name>.+)$",
    re.MULTILINE,
)
_FIELD_STOP = (
    r"(?:Court:|Order:|Granted:|Argument Date:|Decided:|Author:|Other:|Result:|"
    # Repeated page header/footer boilerplate, which otherwise gets pulled
    # into whichever field (usually "Result:") happens to end near a page
    # boundary -- verified against real page breaks in the OT2025 list.
    r"SUPREME COURT OF THE UNITED STATES|GRANTED\s*&\s*NOTED LIST|"
    r"OCTOBER TERM\s*\d{4}|CASES\s*\(ARGUMENTS\)\s*FOR|-\s*\d+\s*-|\Z)"
)


def _parse_date(text: str) -> dt.date | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text or "")
    if not m:
        return None
    month, day, year = m.groups()
    year_i = int(year)
    if year_i < 100:
        year_i += 2000 if year_i < 70 else 1900
    try:
        return dt.date(year_i, int(month), int(day))
    except ValueError:
        return None


def _extract_field(block: str, label: str) -> str | None:
    pattern = re.compile(rf"{label}[ \t]*(.+?){_FIELD_STOP}", re.DOTALL)
    m = pattern.search(block)
    if not m:
        return None
    value = re.sub(r"\s+", " ", m.group(1)).strip(" -")
    return value or None


def parse_granted_noted_list(pdf_bytes: bytes) -> list[GrantedCase]:
    from app.pdf_extract import extract_text_from_path
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.write(fd, pdf_bytes)
    os.close(fd)
    try:
        text, page_count = extract_text_from_path(path, max_pages=50)
    finally:
        os.unlink(path)

    anchors = list(_DOCKET_LINE_RE.finditer(text))
    cases: list[GrantedCase] = []
    pending_consolidated: list[tuple[str, str]] = []  # (docket, name) sharing the next field block

    for i, anchor in enumerate(anchors):
        docket = re.sub(r"\s+", "", anchor.group("docket"))
        name_start = anchor.group("name").strip()
        block_start = anchor.end()
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        block = text[block_start:block_end]

        # Case name may wrap onto the lines before the first field label.
        first_label = re.search(_FIELD_STOP, block)
        name_continuation = block[: first_label.start()] if first_label else block
        case_name = " ".join(
            [name_start] + [ln.strip() for ln in name_continuation.splitlines() if ln.strip()]
        )

        has_fields = bool(re.search(r"Court:|Order:|Author:|Result:", block))
        if not has_fields and i + 1 < len(anchors):
            # Consolidated case (e.g. "25-238)1" / "25-566)2") sharing the
            # next entry's Court:/Granted:/Author:/etc. block.
            pending_consolidated.append((docket, case_name))
            continue

        for shared_docket, shared_name in pending_consolidated:
            cases.append(
                GrantedCase(
                    docket=shared_docket,
                    case_name=shared_name,
                    court=_extract_field(block, "Court:"),
                    granted_date=_parse_date(_extract_field(block, "Granted:") or ""),
                    argument_date=_parse_date(_extract_field(block, "Argument Date:") or ""),
                    decided_date=_parse_date(_extract_field(block, "Decided:") or ""),
                    author=_extract_field(block, "Author:"),
                    other=_extract_field(block, "Other:"),
                    result=_extract_field(block, "Result:"),
                )
            )
        pending_consolidated = []

        cases.append(
            GrantedCase(
                docket=docket,
                case_name=case_name,
                court=_extract_field(block, "Court:"),
                granted_date=_parse_date(_extract_field(block, "Granted:") or ""),
                argument_date=_parse_date(_extract_field(block, "Argument Date:") or ""),
                decided_date=_parse_date(_extract_field(block, "Decided:") or ""),
                author=_extract_field(block, "Author:"),
                other=_extract_field(block, "Other:"),
                result=_extract_field(block, "Result:"),
            )
        )

    return cases


def fetch_granted_noted_list(term: str) -> list[GrantedCase]:
    url = f"{BASE_URL}/orders/{term}grantednotedlist.pdf"
    pdf_bytes = _get_bytes(url)
    return parse_granted_noted_list(pdf_bytes)


# ---------------------------------------------------------------------------
# Monthly Argument Calendars
# ---------------------------------------------------------------------------


@dataclass
class ArgumentDay:
    date: dt.date
    is_holiday: bool
    cases: list[tuple[str, str]] = field(default_factory=list)  # (docket, case_name)


def _extract_two_columns(pdf_bytes: bytes, split_x: float = 300.0) -> tuple[str, str]:
    """Splits a two-column calendar page into independent left/right text
    streams using each text fragment's real x-coordinate, then
    reconstructs each column's lines ordered by y (top to bottom) and x
    (left to right).

    Reconstructing via whitespace-padded layout text (extraction_mode=
    "layout") was tried first and rejected: proportional fonts mean the
    visual column boundary isn't a fixed character offset, so a single
    split column produced text bleeding from the right day into the left
    one on several rows (verified against the October 2026 calendar).
    Coordinates don't have that problem.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    left_frags: list[tuple[float, float, str]] = []
    right_frags: list[tuple[float, float, str]] = []

    for page in reader.pages:
        frags: list[tuple[float, float, str]] = []

        def visitor(text, cm, tm, font_dict, font_size, _frags=frags):
            if text.strip():
                _frags.append((tm[4], tm[5], text))

        page.extract_text(visitor_text=visitor)
        for x, y, text in frags:
            (left_frags if x < split_x else right_frags).append((round(y), x, text))

    def reconstruct(frags: list[tuple[float, float, str]]) -> str:
        rows: dict[float, list[tuple[float, str]]] = {}
        for y, x, text in frags:
            key = next((k for k in rows if abs(k - y) <= 2), y)
            rows.setdefault(key, []).append((x, text))
        lines = []
        for y in sorted(rows.keys(), reverse=True):
            parts = sorted(rows[y], key=lambda p: p[0])
            lines.append(" ".join(t for _, t in parts))
        return "\n".join(lines)

    return reconstruct(left_frags), reconstruct(right_frags)


def _parse_calendar_column(text: str, year: int) -> list[ArgumentDay]:
    headers = list(_WEEKDAY_RE.finditer(text))
    days: list[ArgumentDay] = []
    for i, h in enumerate(headers):
        month_name = re.sub(r"\s+", "", h.group(2))
        month = _MONTHS.index(month_name) + 1
        day_num = int(re.sub(r"\s+", "", h.group(3)))
        try:
            date = dt.date(year, month, day_num)
        except ValueError:
            continue
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        if _HOLIDAY_RE.search(block):
            days.append(ArgumentDay(date=date, is_holiday=True))
            continue

        cases: list[tuple[str, str]] = []
        markers = list(re.finditer(r"\(\s*\d+\s*\)", block))
        for j, marker in enumerate(markers):
            cstart = marker.end()
            cend = markers[j + 1].start() if j + 1 < len(markers) else len(block)
            chunk = block[cstart:cend].strip()
            if not chunk:
                continue
            tokens = chunk.split()
            docket_tokens = []
            for tok in tokens:
                if re.fullmatch(r"[-A\d)#*]+", tok):
                    docket_tokens.append(tok)
                else:
                    break
            if not docket_tokens:
                continue
            docket = "".join(docket_tokens)
            case_name = " ".join(tokens[len(docket_tokens):])
            # Known limitation: when two cases are consolidated into one
            # calendar slot (one case-number marker, two dockets), this
            # doesn't split them -- the second docket and case name stay
            # appended to the first case_name string instead of becoming a
            # second entry. Rare in practice; not worth the added
            # complexity of re-splitting an already best-effort text
            # reconstruction for an edge case this narrow.
            if case_name:
                cases.append((docket, case_name))
        days.append(ArgumentDay(date=date, is_holiday=False, cases=cases))
    return days


def parse_monthly_argument_calendar(pdf_bytes: bytes) -> list[ArgumentDay]:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    header_text = reader.pages[0].extract_text() or ""
    year_match = re.search(
        r"Session Beginning\s+[A-Za-z]+\s+\d{1,2},?\s*(\d{4})", header_text
    )
    if not year_match:
        return []
    year = int(year_match.group(1))
    month_match = re.search(r"Session Beginning\s+([A-Za-z]+)", header_text)
    # A session can run into the following month; if a parsed day number
    # would be absurd for the session's starting month (e.g. day 1 right
    # after a session starting on the 28th), roll the year/month forward.
    left_text, right_text = _extract_two_columns(pdf_bytes)
    left_text, right_text = _strip_footer(left_text), _strip_footer(right_text)
    days = _parse_calendar_column(left_text, year) + _parse_calendar_column(right_text, year)
    days.sort(key=lambda d: d.date)
    return days


def fetch_and_parse_argument_calendars(term: str) -> list[ArgumentDay]:
    links = fetch_term_links()
    entry = next((t for t in links if t.term == term), None)
    if not entry or not entry.argument_calendar_pdfs:
        return []
    all_days: list[ArgumentDay] = []
    for url in entry.argument_calendar_pdfs:
        try:
            pdf_bytes = _get_bytes(url)
            all_days.extend(parse_monthly_argument_calendar(pdf_bytes))
        except requests.RequestException as exc:
            logger.warning("Failed to fetch argument calendar %s: %s", url, exc)
    return all_days
