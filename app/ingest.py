"""Orchestrates a full fetch: scrape listings, upsert into the DB, then
download + extract + summarize any newly-seen PDFs."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from app.config import TERMS
from app.db import session_scope
from app.models import FetchRun, Opinion, Order
from app.pdf_extract import PdfExtractionError, fetch_and_extract
from app.scraper import fetch_all
from app.summarizer import is_notable, summarize

logger = logging.getLogger(__name__)


def _upsert_opinions(session, scraped) -> int:
    new_count = 0
    for item in scraped:
        existing = session.execute(
            select(Opinion).where(Opinion.pdf_url == item.pdf_url)
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(
            Opinion(
                term=item.term,
                rank=item.rank,
                date=item.date,
                docket=item.docket,
                case_name=item.case_name,
                justice=item.justice,
                citation=item.citation,
                pdf_url=item.pdf_url,
                holding=item.holding,
                is_revision=item.is_revision,
            )
        )
        new_count += 1
    return new_count


def _upsert_orders(session, scraped) -> int:
    new_count = 0
    for item in scraped:
        existing = session.execute(
            select(Order).where(Order.pdf_url == item.pdf_url)
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(
            Order(
                term=item.term,
                date=item.date,
                order_type=item.order_type,
                pdf_url=item.pdf_url,
            )
        )
        new_count += 1
    return new_count


def _process_pending_opinions(session, limit: int | None = None) -> None:
    query = select(Opinion).where(Opinion.full_text.is_(None), Opinion.extraction_error.is_(None))
    if limit:
        query = query.limit(limit)
    for opinion in session.execute(query).scalars():
        try:
            text, pages = fetch_and_extract(opinion.pdf_url)
            opinion.full_text = text
            opinion.page_count = pages
            opinion.summary = summarize(text, opinion.case_name, "opinion")
        except PdfExtractionError as exc:
            logger.warning("Failed to extract opinion %s: %s", opinion.pdf_url, exc)
            opinion.extraction_error = str(exc)[:2000]
        except Exception as exc:  # network errors etc.
            logger.warning("Failed to fetch opinion %s: %s", opinion.pdf_url, exc)
            opinion.extraction_error = str(exc)[:2000]


def _process_pending_orders(session, limit: int | None = None) -> None:
    query = select(Order).where(Order.full_text.is_(None), Order.extraction_error.is_(None))
    if limit:
        query = query.limit(limit)
    for order in session.execute(query).scalars():
        try:
            text, pages = fetch_and_extract(order.pdf_url)
            order.full_text = text
            order.page_count = pages
            order.summary = summarize(text, f"{order.order_type} ({order.date})", "order")
            order.notable = is_notable(text)
        except PdfExtractionError as exc:
            logger.warning("Failed to extract order %s: %s", order.pdf_url, exc)
            order.extraction_error = str(exc)[:2000]
        except Exception as exc:
            logger.warning("Failed to fetch order %s: %s", order.pdf_url, exc)
            order.extraction_error = str(exc)[:2000]


def run_fetch(terms: list[str] | None = None, process_documents: bool = True,
              document_limit: int | None = 25) -> dict:
    """Scrapes listings for the given terms, stores new items, and extracts
    text/summaries for a batch of previously-unprocessed documents.

    document_limit caps how many PDFs are downloaded+processed per run so a
    single fetch (e.g. triggered from the API) stays fast; the scheduler
    calls this repeatedly so backlogs drain over subsequent runs.
    """
    terms = terms or TERMS
    with session_scope() as session:
        run = FetchRun(status="running")
        session.add(run)
        session.flush()

        try:
            scraped = fetch_all(terms)
            new_opinions = _upsert_opinions(session, scraped.opinions)
            new_orders = _upsert_orders(session, scraped.orders)
            session.flush()

            if process_documents:
                _process_pending_opinions(session, limit=document_limit)
                _process_pending_orders(session, limit=document_limit)

            run.new_opinions = new_opinions
            run.new_orders = new_orders
            run.status = "error" if scraped.errors else "success"
            run.error = "; ".join(scraped.errors) if scraped.errors else None
        except Exception as exc:
            logger.exception("Fetch run failed")
            run.status = "error"
            run.error = str(exc)[:2000]
        finally:
            run.finished_at = dt.datetime.utcnow()

        return run.to_dict()
