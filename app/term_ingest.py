"""Refreshes term-level data: the current-term label, the Granted & Noted
List (case counts, majority author, concurrence/dissent breakdown), and
the monthly Argument Calendars. This changes far less often than the
opinions/orders listings, so each term is only re-fetched once its
TermSummary row is older than TERM_DATA_REFRESH_HOURS.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

from sqlalchemy import func, select

from app.config import QP_FETCH_LIMIT, TERM_DATA_REFRESH_HOURS, TERMS
from app.db import session_scope
from app.dockets import normalize_docket
from app.models import ArgumentEntry, Opinion, QuestionPresented, TermSummary
from app.qp_scraper import fetch_qp
from app.term_scraper import (
    fetch_and_parse_argument_calendars,
    fetch_granted_noted_list,
    fetch_term_links,
    get_current_and_next_term,
)
from app.votes import has_dissent

logger = logging.getLogger(__name__)

_AUTHOR_PREFIX_RE = re.compile(r"^J\.\s*")


def _clean_author(raw: str | None) -> str | None:
    if not raw:
        return None
    return _AUTHOR_PREFIX_RE.sub("", raw).strip() or None


def _is_stale(term: str) -> bool:
    with session_scope() as session:
        row = session.get(TermSummary, term)
        if row is None:
            return True
        # A previous failed fetch leaves source_error set and must not
        # sit on the 12h cache -- otherwise a transient 404/timeout
        # silences retries until the clock runs out.
        if row.source_error:
            return True
        age = dt.datetime.utcnow() - row.fetched_at
        return age.total_seconds() > TERM_DATA_REFRESH_HOURS * 3600


def _term_has_unmatched_opinions(term: str) -> bool:
    """True when this term has decided opinions that still lack Granted &
    Noted List metadata. Used to re-download a "fresh" list after new
    opinions land, instead of waiting the full refresh window."""
    with session_scope() as session:
        unmatched = session.execute(
            select(func.count(Opinion.id)).where(
                Opinion.term == term,
                Opinion.docket.isnot(None),
                Opinion.author_name.is_(None),
                Opinion.separate_opinions.is_(None),
            )
        ).scalar_one()
        return unmatched > 0


def _refresh_granted_list(term: str, label: str, is_current: bool) -> list | None:
    try:
        cases = fetch_granted_noted_list(term)
    except Exception as exc:
        logger.warning("Failed to fetch granted/noted list for term %s: %s", term, exc)
        with session_scope() as session:
            existing = session.get(TermSummary, term)
            if existing is None:
                session.add(
                    TermSummary(
                        term=term,
                        label=label,
                        is_current=is_current,
                        total_granted=0,
                        # Epoch so _is_stale immediately retries rather
                        # than caching a failed fetch for 12 hours.
                        fetched_at=dt.datetime(1970, 1, 1),
                        source_error=str(exc)[:500],
                    )
                )
            else:
                existing.label = label
                existing.is_current = is_current
                existing.source_error = str(exc)[:500]
        return None

    with session_scope() as session:
        session.merge(
            TermSummary(
                term=term,
                label=label,
                is_current=is_current,
                total_granted=len(cases),
                fetched_at=dt.datetime.utcnow(),
                source_error=None,
            )
        )

        opinions = session.execute(select(Opinion).where(Opinion.term == term)).scalars().all()
        by_docket: dict[str, list] = {}
        for opinion in opinions:
            key = normalize_docket(opinion.docket)
            if key:
                by_docket.setdefault(key, []).append(opinion)

        matched = 0
        for case in cases:
            key = normalize_docket(case.docket)
            for opinion in by_docket.get(key, []):
                opinion.granted_date = case.granted_date
                opinion.argument_date = case.argument_date
                opinion.author_name = _clean_author(case.author)
                opinion.separate_opinions = case.other
                opinion.disposition = case.result
                opinion.has_dissent = has_dissent(case.other)
                matched += 1
        logger.info(
            "Granted-list match for OT%s: %d cases, %d opinion row(s) updated",
            term, len(cases), matched,
        )

    return cases


def _refresh_questions_presented(term: str, cases: list, limit: int = QP_FETCH_LIMIT) -> None:
    """Fetches the Questions Presented PDF for cases in this term that
    don't have one stored yet, capped at `limit` per call -- a term can
    have 60+ granted cases, and each QP rarely if ever changes once set,
    so there's no reason to re-fetch ones already on file."""
    with session_scope() as session:
        known_dockets = set(
            session.execute(
                select(QuestionPresented.docket).where(QuestionPresented.term == term)
            ).scalars()
        )

    pending = [c for c in cases if c.docket not in known_dockets][:limit]
    for case in pending:
        record = fetch_qp(case.docket)
        with session_scope() as session:
            if record is None:
                session.add(
                    QuestionPresented(term=term, docket=case.docket, not_available=True)
                )
            else:
                session.add(
                    QuestionPresented(
                        term=term,
                        docket=case.docket,
                        case_name=record.case_name or case.case_name,
                        decision_below=record.decision_below,
                        lower_court_case_number=record.lower_court_case_number,
                        question_presented=record.question_presented,
                        status_line=record.status_line,
                    )
                )


def _refresh_argument_calendar(term: str) -> None:
    try:
        days = fetch_and_parse_argument_calendars(term)
    except Exception as exc:
        logger.warning("Failed to fetch argument calendar for term %s: %s", term, exc)
        return

    with session_scope() as session:
        for day in days:
            if day.is_holiday:
                continue
            for docket, case_name in day.cases:
                existing = session.execute(
                    select(ArgumentEntry).where(
                        ArgumentEntry.term == term,
                        ArgumentEntry.date == day.date,
                        ArgumentEntry.docket == docket,
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.case_name = case_name
                else:
                    session.add(
                        ArgumentEntry(
                            term=term, date=day.date, docket=docket, case_name=case_name
                        )
                    )


def refresh_term_data(force: bool = False) -> None:
    current_term, next_term = get_current_and_next_term()

    try:
        links = fetch_term_links()
    except Exception as exc:
        logger.warning("Failed to fetch term links: %s", exc)
        links = []
    labels = {t.term: t.label for t in links}

    planned: list[tuple[str, bool]] = []
    seen: set[str] = set()
    if current_term:
        planned.append((current_term, True))
        seen.add(current_term)
    if next_term and next_term not in seen:
        planned.append((next_term, False))
        seen.add(next_term)
    # Also refresh every configured tracked term (e.g. the previous OT).
    # Restricting to current+next left OT24 opinions with no author /
    # dissent metadata even though TERMS includes "24".
    for term in TERMS:
        if term not in seen:
            planned.append((term, False))
            seen.add(term)

    if not planned:
        logger.info("Could not determine any term to refresh; skipping term data")
        return

    for term, is_current in planned:
        if not force and not _is_stale(term) and not _term_has_unmatched_opinions(term):
            continue
        try:
            year = 2000 + int(term)
        except ValueError:
            year = 2000
        label = labels.get(term, f"October Term {year}")
        cases = _refresh_granted_list(term, label, is_current)
        _refresh_argument_calendar(term)
        if cases:
            _refresh_questions_presented(term, cases)


def get_questions_presented(term: str) -> list[dict]:
    """All QPs fetched so far for a term, ordered by docket. Cases whose QP
    hasn't been fetched yet (see QP_FETCH_LIMIT) simply won't appear until
    a later refresh catches up."""
    with session_scope() as session:
        rows = session.execute(
            select(QuestionPresented)
            .where(QuestionPresented.term == term, QuestionPresented.not_available.is_(False))
            .order_by(QuestionPresented.docket)
        ).scalars().all()
        return [r.to_dict() for r in rows]


def get_next_argument_days(limit_days: int = 1) -> list[dict]:
    """Returns the next `limit_days` distinct upcoming argument dates (each
    with its cases), across whichever terms have data -- since a term's
    argument sessions can be entirely in the past while the *next* term's
    haven't started yet (e.g. during summer recess)."""
    today = dt.date.today()
    with session_scope() as session:
        dates = session.execute(
            select(ArgumentEntry.date)
            .where(ArgumentEntry.date >= today)
            .distinct()
            .order_by(ArgumentEntry.date)
            .limit(limit_days)
        ).scalars().all()
        if not dates:
            return []
        entries = session.execute(
            select(ArgumentEntry)
            .where(ArgumentEntry.date.in_(dates))
            .order_by(ArgumentEntry.date, ArgumentEntry.id)
        ).scalars().all()

        by_date: dict[dt.date, list[dict]] = {}
        for e in entries:
            by_date.setdefault(e.date, []).append({"docket": e.docket, "case_name": e.case_name})
        return [{"date": d.isoformat(), "cases": by_date[d]} for d in dates]
