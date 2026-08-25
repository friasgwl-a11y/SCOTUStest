"""Orchestrates a full fetch: scrape listings, upsert into the DB, then
download + extract + summarize any newly-seen PDFs.

Durability note: each stage commits in its own transaction, and each PDF
commits individually as it finishes. An earlier version wrapped the whole
run in a single transaction, which meant a run that was interrupted
partway through PDF processing (OOM, timeout, or a host spinning the
process down -- all easy to hit on small/free hosting tiers) rolled back
the listing scrape too, leaving the database permanently empty. Committing
incrementally means partial progress always survives and later runs resume
where the last one stopped.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from app.config import DOCUMENT_LIMIT, TERMS
from app.db import session_scope
from app.models import FetchRun, Opinion, Order
from app.pdf_extract import fetch_and_extract
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


def _pending_ids(model, limit: int) -> list[int]:
    with session_scope() as session:
        return list(
            session.execute(
                select(model.id)
                .where(model.full_text.is_(None), model.extraction_error.is_(None))
                .order_by(model.date.desc().nulls_last(), model.id.desc())
                .limit(limit)
            ).scalars()
        )


def _process_pending_opinions(limit: int) -> tuple[int, int, str | None]:
    """Returns (succeeded, failed, first_error)."""
    ok = failed = 0
    first_error: str | None = None
    for opinion_id in _pending_ids(Opinion, limit):
        # One transaction per document, so each finished opinion is durable
        # even if the run is interrupted before the rest are processed.
        with session_scope() as session:
            opinion = session.get(Opinion, opinion_id)
            if opinion is None:
                continue
            try:
                text, pages = fetch_and_extract(opinion.pdf_url)
                opinion.full_text = text
                opinion.page_count = pages
                opinion.summary = summarize(text, opinion.case_name, "opinion")
                ok += 1
            except Exception as exc:
                logger.warning("Failed to process opinion %s: %s", opinion.pdf_url, exc)
                opinion.extraction_error = str(exc)[:2000]
                failed += 1
                first_error = first_error or f"{type(exc).__name__}: {exc}"
    return ok, failed, first_error


def _process_pending_orders(limit: int) -> tuple[int, int, str | None]:
    """Returns (succeeded, failed, first_error)."""
    ok = failed = 0
    first_error: str | None = None
    for order_id in _pending_ids(Order, limit):
        with session_scope() as session:
            order = session.get(Order, order_id)
            if order is None:
                continue
            try:
                text, pages = fetch_and_extract(order.pdf_url)
                order.full_text = text
                order.page_count = pages
                order.summary = summarize(text, f"{order.order_type} ({order.date})", "order")
                order.notable = is_notable(text)
                ok += 1
            except Exception as exc:
                logger.warning("Failed to process order %s: %s", order.pdf_url, exc)
                order.extraction_error = str(exc)[:2000]
                failed += 1
                first_error = first_error or f"{type(exc).__name__}: {exc}"
    return ok, failed, first_error


def run_fetch(terms: list[str] | None = None, process_documents: bool = True,
              document_limit: int | None = None) -> dict:
    """Scrapes listings for the given terms, stores new items, and extracts
    text/summaries for a batch of previously-unprocessed documents.

    document_limit caps how many PDFs are downloaded+processed per run so a
    single fetch stays fast; the scheduler calls this repeatedly so backlogs
    drain over subsequent runs.
    """
    terms = terms or TERMS
    if document_limit is None:
        document_limit = DOCUMENT_LIMIT

    with session_scope() as session:
        run = FetchRun(status="running")
        session.add(run)
        session.flush()
        run_id = run.id

    new_opinions = 0
    new_orders = 0
    status = "success"
    error_text: str | None = None

    try:
        # Stage 1: scrape the listing pages and commit them immediately, so
        # the catalogue survives even if PDF processing later fails.
        with session_scope() as session:
            scraped = fetch_all(terms)
            new_opinions = _upsert_opinions(session, scraped.opinions)
            new_orders = _upsert_orders(session, scraped.orders)

        if scraped.errors:
            status = "error"
            error_text = "; ".join(scraped.errors)[:2000]

        # Stage 2: process a batch of PDFs, committing each one as it lands.
        if process_documents:
            op_ok, op_failed, op_err = _process_pending_opinions(document_limit)
            or_ok, or_failed, or_err = _process_pending_orders(document_limit)
            attempted = op_ok + op_failed + or_ok + or_failed
            failed = op_failed + or_failed
            # Every single document failing points at something systemic
            # (e.g. the Court's site refusing requests from this host)
            # rather than one malformed PDF, so surface it prominently.
            if attempted and failed == attempted:
                status = "error"
                error_text = (
                    f"All {failed} document download(s) failed. "
                    f"First error: {op_err or or_err}"
                )[:2000]
            elif failed:
                logger.info("%d of %d documents failed this run", failed, attempted)
    except Exception as exc:
        logger.exception("Fetch run failed")
        status = "error"
        error_text = str(exc)[:2000]

    with session_scope() as session:
        run = session.get(FetchRun, run_id)
        run.new_opinions = new_opinions
        run.new_orders = new_orders
        run.status = status
        run.error = error_text
        run.finished_at = dt.datetime.utcnow()
        return run.to_dict()
