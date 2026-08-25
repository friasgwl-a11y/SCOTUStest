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

from sqlalchemy import select

from app.config import QP_FETCH_LIMIT, TERM_DATA_REFRESH_HOURS
from app.db import session_scope
from app.models import ArgumentEntry, Opinion, QuestionPresented, TermSummary
from app.qp_scraper import fetch_qp
from app.term_scraper import (
    fetch_and_parse_argument_calendars,
    fetch_granted_noted_list,
    fetch_term_links,
    get_current_and_next_term,
)

logger = logging.getLogger(__name__)

_AUTHOR_PREFIX_RE = re.compile(r"^J\.\s*")
_DISSENT_CODE_RE = re.compile(r"\(([CDJP/,\s]*)\)")


def _clean_author(raw: str | None) -> str | None:
    if not raw:
        return None
    return _AUTHOR_PREFIX_RE.sub("", raw).strip() or None


def _has_dissent(other_text: str | None) -> bool:
    if not other_text:
        return False
    for m in _DISSENT_CODE_RE.finditer(other_text):
        if re.search(r"(?<![A-Z])D(?![A-Za-z])", m.group(1)):
            return True
    return False


def _is_stale(term: str) -> bool:
    with session_scope() as session:
        row = session.get(TermSummary, term)
        if row is None:
            return True
        age = dt.datetime.utcnow() - row.fetched_at
        return age.total_seconds() > TERM_DATA_REFRESH_HOURS * 3600


def _refresh_granted_list(term: str, label: str, is_current: bool) -> list | None:
    try:
        cases = fetch_granted_noted_list(term)
    except Exception as exc:
        logger.warning("Failed to fetch granted/noted list for term %s: %s", term, exc)
        with session_scope() as session:
            existing = session.get(TermSummary, term)
            session.add(
                TermSummary(
                    term=term,
                    label=label,
                    is_current=is_current,
                    total_granted=existing.total_granted if existing else 0,
                    fetched_at=dt.datetime.utcnow(),
                    source_error=str(exc)[:500],
                )
            )
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

        for case in cases:
            opinion = session.execute(
                select(Opinion).where(Opinion.term == term, Opinion.docket == case.docket)
            ).scalars().first()
            if not opinion:
                continue
            opinion.granted_date = case.granted_date
            opinion.argument_date = case.argument_date
            opinion.author_name = _clean_author(case.author)
            opinion.separate_opinions = case.other
            opinion.disposition = case.result
            opinion.has_dissent = _has_dissent(case.other)

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
    if not current_term:
        logger.info("Could not determine current term from the Court's site; skipping term data refresh")
        return

    try:
        links = fetch_term_links()
    except Exception as exc:
        logger.warning("Failed to fetch term links: %s", exc)
        links = []
    labels = {t.term: t.label for t in links}

    for term, is_current in [(current_term, True), (next_term, False)]:
        if not term:
            continue
        if not force and not _is_stale(term):
            continue
        label = labels.get(term, f"October Term {2000 + int(term)}")
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
