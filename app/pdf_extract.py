"""Downloads a SCOTUS PDF (opinion or order) and extracts its plain text."""

from __future__ import annotations

import io
import logging

import pdfplumber
import requests

from app.config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 25 * 1024 * 1024  # guard against unexpectedly huge documents


class PdfExtractionError(Exception):
    pass


def download_pdf(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            raise PdfExtractionError(f"PDF exceeds size limit ({MAX_PDF_BYTES} bytes): {url}")
        chunks.append(chunk)
    return b"".join(chunks)


def extract_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Returns (full_text, page_count)."""
    text_parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
    except Exception as exc:  # pdfplumber/pdfminer raise various exception types
        raise PdfExtractionError(str(exc)) from exc

    return "\n\n".join(text_parts).strip(), page_count


def fetch_and_extract(url: str) -> tuple[str, int]:
    pdf_bytes = download_pdf(url)
    return extract_text(pdf_bytes)
