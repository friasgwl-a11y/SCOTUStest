from __future__ import annotations

import datetime as dt
import threading

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.config import TERMS
from app.db import session_scope
from app.ingest import run_fetch
from app.models import FetchRun, Opinion, Order

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


@router.get("/opinions")
def list_opinions(
    term: str | None = None,
    justice: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with session_scope() as session:
        stmt = select(Opinion)
        if term:
            stmt = stmt.where(Opinion.term == term)
        if justice:
            stmt = stmt.where(Opinion.justice == justice)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Opinion.case_name.ilike(like),
                    Opinion.docket.ilike(like),
                    Opinion.holding.ilike(like),
                )
            )
        total = session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        stmt = stmt.order_by(Opinion.date.desc().nulls_last(), Opinion.id.desc())
        stmt = stmt.limit(limit).offset(offset)
        items = session.execute(stmt).scalars().all()
        return {
            "total": total,
            "items": [o.to_dict() for o in items],
        }


@router.get("/opinions/{opinion_id}")
def get_opinion(opinion_id: int):
    with session_scope() as session:
        opinion = session.get(Opinion, opinion_id)
        if not opinion:
            raise HTTPException(status_code=404, detail="Opinion not found")
        return opinion.to_dict(include_full_text=True)


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
        return order.to_dict(include_full_text=True)


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
