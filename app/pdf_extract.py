"""Downloads a SCOTUS PDF (opinion or order) and extracts its plain text.

Memory notes -- this runs on small hosting tiers (512MB), so the whole
path is written to keep peak RSS low:

  * pypdf, not pdfplumber. Measured on a 77-page slip opinion, pdfplumber
    peaked at ~354MB while pypdf peaked at ~39MB for the same document
    (and extracted slightly more text). pdfplumber's layout/table analysis
    is what costs that memory, and we only need the plain text.
  * The download streams to a temporary file rather than being held in
    memory, so the raw PDF bytes never occupy RSS.
  * Only the first MAX_PDF_PAGES pages are read. A slip opinion's syllabus
    and holding live at the front; the tail is separate opinions and
    appendices that add memory without improving the summary.
  * Page text is released as we go and the extracted text is capped, so a
    pathologically long document cannot balloon the process.
"""

from __future__ import annotations

import gc
import logging
import os
import tempfile

import requests
from pypdf import PdfReader

from app.config import MAX_PDF_PAGES, MAX_STORED_TEXT_CHARS, REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 25 * 1024 * 1024  # guard against unexpectedly huge documents


class PdfExtractionError(Exception):
    pass


def _download_to_tempfile(url: str) -> str:
    """Streams the PDF to a temp file. Returns the path; caller deletes it."""
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()

    fd, path = tempfile.mkstemp(suffix=".pdf")
    total = 0
    try:
        with os.fdopen(fd, "wb") as handle:
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise PdfExtractionError(
                        f"PDF exceeds size limit ({MAX_PDF_BYTES} bytes): {url}"
                    )
                handle.write(chunk)
    except Exception:
        os.unlink(path)
        raise
    finally:
        resp.close()
    return path


def extract_text_from_path(path: str, max_pages: int = MAX_PDF_PAGES) -> tuple[str, int]:
    """Returns (text, total_page_count). Reads at most max_pages pages."""
    parts: list[str] = []
    size = 0
    try:
        reader = PdfReader(path)
        page_count = len(reader.pages)
        for index, page in enumerate(reader.pages):
            if index >= max_pages:
                break
            try:
                # layout mode keeps words intact. pypdf's default mode is
                # over-eager about inserting spaces on the kerned fonts in
                # these PDFs, producing breaks like "United Stat es" and
                # "Four teenth" that then poison the summaries. Layout mode
                # costs no additional memory (measured identical peak RSS).
                page_text = page.extract_text(extraction_mode="layout") or ""
            except Exception as exc:  # a single malformed page shouldn't sink the doc
                logger.debug("Page %d of %s failed to extract: %s", index, path, exc)
                continue
            parts.append(page_text)
            size += len(page_text)
            if size >= MAX_STORED_TEXT_CHARS:
                break
    except PdfExtractionError:
        raise
    except Exception as exc:  # pypdf raises assorted exception types
        raise PdfExtractionError(str(exc)) from exc

    text = "\n\n".join(parts)[:MAX_STORED_TEXT_CHARS].strip()
    del parts
    return text, page_count


def fetch_and_extract(url: str, max_pages: int = MAX_PDF_PAGES) -> tuple[str, int]:
    path = _download_to_tempfile(url)
    try:
        return extract_text_from_path(path, max_pages=max_pages)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        # Release pypdf's per-document object graph before the next document.
        gc.collect()
