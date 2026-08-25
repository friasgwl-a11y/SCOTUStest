from __future__ import annotations

import datetime as dt
import threading

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.config import RECENT_OPINION_DAYS, TERMS
from app.db import session_scope
from app.ingest import ensure_separate_opinions, process_document, run_fetch
from app.models import FetchRun, Opinion, Order, TermSummary
from app.term_ingest import get_next_argument_days, get_questions_presented

router = APIRouter(prefix="/api")

_refresh_lock = threading.Lock()
_refresh_running = False


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/stats")
def stats():
    with session_scope() as session:
        total_opinions = session.execute(select(func.count(Opinion.id))).scalar_one()
        total_orders = session.execute(select(func.count(Order.id))).scalar_one()
        notable_orders = session.execute(
            select(func.count(Order.id)).where(Order.notable.is_(True))
        ).scalar_one()

        by_term_opinions = dict(
            session.execute(
                select(Opinion.term, func.count(Opinion.id)).group_by(Opinion.term)
            ).all()
        )
        by_term_orders = dict(
            session.execute(
                select(Order.term, func.count(Order.id)).group_by(Order.term)
            ).all()
        )

        latest_opinion = session.execute(
            select(Opinion).order_by(Opinion.date.desc().nulls_last()).limit(1)
        ).scalar_one_or_none()
        latest_order = session.execute(
            select(Order).order_by(Order.date.desc().nulls_last()).limit(1)
        ).scalar_one_or_none()

        justices = [
            j for (j,) in session.execute(
                select(Opinion.justice).distinct().where(Opinion.justice.isnot(None))
            ).all()
        ]

        last_run = session.execute(
            select(FetchRun).order_by(FetchRun.id.desc()).limit(1)
        ).scalar_one_or_none()

        pending_opinions = session.execute(
            select(func.count(Opinion.id)).where(
                Opinion.full_text.is_(None), Opinion.extraction_error.is_(None)
            )
        ).scalar_one()
        pending_orders = session.execute(
            select(func.count(Order.id)).where(
                Order.full_text.is_(None), Order.extraction_error.is_(None)
            )
        ).scalar_one()

        return {
            "total_opinions": total_opinions,
            "total_orders": total_orders,
            "notable_orders": notable_orders,
            "by_term_opinions": by_term_opinions,
            "by_term_orders": by_term_orders,
            "latest_opinion_date": latest_opinion.date.isoformat()
            if latest_opinion and latest_opinion.date
            else None,
            "latest_order_date": latest_order.date.isoformat()
            if latest_order and latest_order.date
            else None,
            "last_fetch_run": last_run.to_dict() if last_run else None,
            "pending_opinions": pending_opinions,
            "pending_orders": pending_orders,
            "tracked_terms": TERMS,
            "justices": sorted(justices),
            "refresh_running": _refresh_running,
        }


_OPINION_SORTS = {
    "date_desc": (Opinion.date.desc().nulls_last(), Opinion.id.desc()),
    "date_asc": (Opinion.date.asc().nulls_last(), Opinion.id.desc()),
    "author": (Opinion.author_name.asc().nulls_last(), Opinion.date.desc().nulls_last()),
    "docket": (Opinion.docket.asc().nulls_last(),),
}


@router.get("/opinions")
def list_opinions(
    term: str | None = None,
    scope: str | None = Query(None, pattern="^(recent|term|all)$"),
    justice: str | None = None,
    q: str | None = None,
    has_dissent: bool | None = None,
    sort: str = Query("date_desc", pattern="^(date_desc|date_asc|author|docket)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """`scope` partitions the dashboard's default "quick reference" view
    from its "look back further" views: "recent" (the default a fresh
    visitor should land on) restricts to the last RECENT_OPINION_DAYS
    days; "term" restricts to the current term regardless of date; "all"
    (or omitting scope, with an explicit `term` filter instead) applies no
    date/term restriction of its own.
    """
    with session_scope() as session:
        stmt = select(Opinion)
        if scope == "recent":
            since = dt.date.today() - dt.timedelta(days=RECENT_OPINION_DAYS)
            stmt = stmt.where(Opinion.date >= since)
        elif scope == "term":
            current = session.execute(
                select(TermSummary.term).where(TermSummary.is_current.is_(True))
            ).scalar_one_or_none()
            if current:
                stmt = stmt.where(Opinion.term == current)
        if term:
            stmt = stmt.where(Opinion.term == term)
        if justice:
            stmt = stmt.where(Opinion.justice == justice)
        if has_dissent is not None:
            stmt = stmt.where(Opinion.has_dissent.is_(has_dissent))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Opinion.case_name.ilike(like),
                    Opinion.docket.ilike(like),
                    Opinion.holding.ilike(like),
                    Opinion.author_name.ilike(like),
                )
            )
        total = session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        stmt = stmt.order_by(*_OPINION_SORTS[sort])
        stmt = stmt.limit(limit).offset(offset)
        items = session.execute(stmt).scalars().all()
        return {
            "total": total,
            "items": [o.to_dict() for o in items],
        }


@router.get("/term-summary")
def term_summary():
    with session_scope() as session:
        current = session.execute(
            select(TermSummary).where(TermSummary.is_current.is_(True))
        ).scalars().first()
        next_summary = None
        if current:
            next_term_code = str(int(current.term) + 1).zfill(2)
            next_summary = session.get(TermSummary, next_term_code)

        return {
            "current_term": current.to_dict() if current else None,
            "next_term": next_summary.to_dict() if next_summary else None,
        }


@router.get("/argument-calendar")
def argument_calendar(days: int = Query(1, ge=1, le=30)):
    return {"upcoming": get_next_argument_days(limit_days=days)}


@router.get("/questions-presented")
def questions_presented(term: str):
    with session_scope() as session:
        summary = session.get(TermSummary, term)
        label = summary.label if summary else None
        total_granted = summary.total_granted if summary else None
    return {
        "term": term,
        "label": label,
        "total_granted": total_granted,
        "items": get_questions_presented(term),
    }


@router.get("/opinions/{opinion_id}")
def get_opinion(opinion_id: int):
    with session_scope() as session:
        opinion = session.get(Opinion, opinion_id)
        if not opinion:
            raise HTTPException(status_code=404, detail="Opinion not found")
        # Cheap, idempotent backfill: separate_opinions (from the Granted &
        # Noted List) and full_text (from the PDF) can each land first
        # depending on fetch timing, so this catches the case where both
        # are now on hand but the split-out concurrence/dissent text
        # hasn't been extracted yet. Never re-downloads the PDF.
        ensure_separate_opinions(session, opinion)
        return opinion.to_dict(detail=True)


@router.get("/orders")
def list_orders(
    term: str | None = None,
    order_type: str | None = None,
    notable: bool | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with session_scope() as session:
        stmt = select(Order)
        if term:
            stmt = stmt.where(Order.term == term)
        if order_type:
            stmt = stmt.where(Order.order_type == order_type)
        if notable is not None:
            stmt = stmt.where(Order.notable.is_(notable))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(Order.summary.ilike(like), Order.full_text.ilike(like))
            )
        total = session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        stmt = stmt.order_by(Order.date.desc().nulls_last(), Order.id.desc())
        stmt = stmt.limit(limit).offset(offset)
        items = session.execute(stmt).scalars().all()
        return {
            "total": total,
            "items": [o.to_dict() for o in items],
        }


@router.get("/orders/{order_id}")
def get_order(order_id: int):
    with session_scope() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order.to_dict()


@router.post("/opinions/{opinion_id}/summarize")
def summarize_opinion(opinion_id: int):
    """Generates this opinion's text + summary on demand.

    Summaries are produced lazily -- only recently released documents are
    processed in the background -- so this is what fills one in the first
    time someone opens an older case. Returns immediately if it is already
    processed.
    """
    result = process_document("opinion", opinion_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Opinion not found")
    return result


@router.post("/orders/{order_id}/summarize")
def summarize_order(order_id: int):
    result = process_document("order", order_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return result


@router.get("/fetch-runs")
def fetch_runs(limit: int = Query(20, ge=1, le=100)):
    with session_scope() as session:
        runs = session.execute(
            select(FetchRun).order_by(FetchRun.id.desc()).limit(limit)
        ).scalars().all()
        return {"items": [r.to_dict() for r in runs]}


def _background_refresh() -> None:
    global _refresh_running
    try:
        run_fetch()
    finally:
        _refresh_running = False


@router.post("/refresh")
def trigger_refresh():
    global _refresh_running
    with _refresh_lock:
        if _refresh_running:
            return {"status": "already_running"}
        _refresh_running = True
    thread = threading.Thread(target=_background_refresh, daemon=True)
    thread.start()
    return {"status": "started", "triggered_at": dt.datetime.utcnow().isoformat()}
