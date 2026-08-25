"""Fetches "Questions Presented" documents -- one PDF per case, published
by the Court at a predictable URL built from the docket number, giving the
exact legal question(s) the Court agreed to decide when it granted or
noted the case.

URL pattern (verified against live docket pages and QP PDFs on
2026-08-25, e.g. https://www.supremecourt.gov/qp/23-01197qp.pdf):

  - A standard cert docket like "24-1021" (term "24", number "1021") is
    zero-padded to 5 digits: /qp/24-01021qp.pdf.
  - An application docket like "25A312" is used as-is, unpadded:
    /qp/25A312qp.pdf.
  - Consolidated-case suffixes ("24-1021)1") and unanimous-decision flags
    ("23-1209*", "24-171#") from the Granted & Noted List are stripped
    before building the URL -- they aren't part of the docket itself.

Not every docket has a QP PDF (some very old or unusual dockets 404);
callers should treat a missing document as "not available" rather than an
error.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

from app.config import BASE_URL, REQUEST_TIMEOUT, USER_AGENT
from app.dockets import normalize_docket

logger = logging.getLogger(__name__)

_APPLICATION_DOCKET_RE = re.compile(r"^(\d+)A(\d+)$")
_CERT_DOCKET_RE = re.compile(r"^(\d+)-(\d+)$")


def normalize_docket_for_qp(raw_docket: str) -> str | None:
    """Strips consolidated-case/unanimous-flag suffixes and returns the QP
    filename stem (without "qp.pdf"), or None if the docket doesn't match
    a known format."""
    docket = normalize_docket(raw_docket)

    if _APPLICATION_DOCKET_RE.match(docket):
        return docket

    m = _CERT_DOCKET_RE.match(docket)
    if m:
        term_part, number_part = m.groups()
        return f"{term_part}-{int(number_part):05d}"

    return None


def qp_url_for_docket(raw_docket: str) -> str | None:
    stem = normalize_docket_for_qp(raw_docket)
    if not stem:
        return None
    return f"{BASE_URL}/qp/{stem}qp.pdf"


@dataclass
class QPRecord:
    case_name: str | None
    decision_below: str | None
    lower_court_case_number: str | None
    question_presented: str
    status_line: str | None


_FIELD_STOP = r"(?:DECISION BELOW:|LOWER COURT CASE NUMBER:|QUESTIONS? PRESENTED:|\Z)"


def parse_qp_pdf(pdf_bytes: bytes) -> QPRecord | None:
    from app.pdf_extract import extract_text_from_path
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.write(fd, pdf_bytes)
    os.close(fd)
    try:
        text, _pages = extract_text_from_path(path, max_pages=5)
    finally:
        os.unlink(path)

    if not text.strip():
        return None

    lines = [ln for ln in text.splitlines() if ln.strip()]
    case_name = None
    if lines:
        # First line is "{docket} {CASE NAME}"; drop the leading docket token.
        first = lines[0].strip()
        m = re.match(r"^\S+\s+(.+)$", first)
        case_name = m.group(1).strip() if m else first

    def field(label: str) -> str | None:
        pattern = re.compile(rf"{label}[ \t]*(.+?){_FIELD_STOP}", re.DOTALL)
        m = pattern.search(text)
        if not m:
            return None
        value = re.sub(r"\s+", " ", m.group(1)).strip(" -")
        return value or None

    decision_below = field("DECISION BELOW:")
    lower_court_case_number = field("LOWER COURT CASE NUMBER:")

    qp_match = re.search(r"QUESTIONS? PRESENTED:(.+)$", text, re.DOTALL)
    if not qp_match:
        return None
    remainder = qp_match.group(1).strip()

    # The document ends with a short status stamp on its own line, e.g.
    # "CERT. GRANTED 7/3/2025" or "JURISDICTION NOTED 10/1/2025" -- split
    # it off as the last non-empty line so it doesn't pollute the QP text.
    remainder_lines = [ln for ln in remainder.splitlines() if ln.strip()]
    status_line = None
    if remainder_lines and re.match(
        r"^[A-Z][A-Z .]+(?:\d{1,2}/\d{1,2}/\d{2,4})?$", remainder_lines[-1].strip()
    ):
        status_line = remainder_lines.pop().strip()
    question_presented = re.sub(r"\s+", " ", "\n".join(remainder_lines)).strip()

    return QPRecord(
        case_name=case_name,
        decision_below=decision_below,
        lower_court_case_number=lower_court_case_number,
        question_presented=question_presented,
        status_line=status_line,
    )


def fetch_qp(raw_docket: str) -> QPRecord | None:
    url = qp_url_for_docket(raw_docket)
    if not url:
        return None
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch QP for docket %s: %s", raw_docket, exc)
        return None
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return parse_qp_pdf(resp.content)
