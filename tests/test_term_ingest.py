"""Granted-list matching: annotated dockets must attach to clean listing
dockets, including every revision row sharing that docket, and a failed
fetch must not freeze retries for 12 hours.
"""

import datetime as dt

import pytest

from app.models import Opinion, TermSummary
from app.term_scraper import GrantedCase


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as db_module
    from app.models import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(
        db_module, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False)
    )
    return db_module


def _seed_opinion(db, **kwargs):
    defaults = dict(
        term="25",
        rank="1",
        date=dt.date(2025, 6, 27),
        docket="24-171",
        case_name="Example v. Test",
        justice="Thomas",
        citation="606",
        pdf_url="https://example.test/a.pdf",
        holding="Reversed.",
        is_revision=False,
    )
    defaults.update(kwargs)
    with db.session_scope() as session:
        row = Opinion(**defaults)
        session.add(row)
        session.flush()
        return row.id


def test_granted_list_matches_despite_suffix_and_updates_all_revisions(db, monkeypatch):
    from app import term_ingest

    original_id = _seed_opinion(db, docket="24-171", pdf_url="https://example.test/a.pdf", is_revision=False)
    revision_id = _seed_opinion(
        db,
        docket="24-171",
        pdf_url="https://example.test/a-rev.pdf",
        is_revision=True,
        rank="1 Rev",
    )
    dissent_id = _seed_opinion(
        db,
        docket="24-820",
        pdf_url="https://example.test/b.pdf",
        case_name="Dissent Case",
        justice="Barrett",
    )

    cases = [
        GrantedCase(
            docket="24-171#",
            case_name="EXAMPLE V. TEST",
            court="USCA-9",
            granted_date=dt.date(2024, 10, 1),
            argument_date=dt.date(2025, 3, 1),
            decided_date=dt.date(2025, 6, 27),
            author="J. Thomas",
            other="Sotomayor (C/J)",
            result="REVERSED AND REMANDED",
        ),
        GrantedCase(
            docket="24-820)",
            case_name="DISSENT CASE",
            court="USCA-5",
            granted_date=dt.date(2024, 11, 1),
            argument_date=dt.date(2025, 4, 1),
            decided_date=dt.date(2025, 6, 27),
            author="J. Barrett",
            other="Sotomayor (D)",
            result="AFFIRMED",
        ),
    ]

    monkeypatch.setattr(term_ingest, "get_current_and_next_term", lambda: ("25", "26"))
    monkeypatch.setattr(term_ingest, "fetch_term_links", lambda: [])
    monkeypatch.setattr(term_ingest, "fetch_granted_noted_list", lambda term: cases if term == "25" else [])
    monkeypatch.setattr(term_ingest, "fetch_and_parse_argument_calendars", lambda term: [])
    monkeypatch.setattr(term_ingest, "fetch_qp", lambda docket: None)
    monkeypatch.setattr(term_ingest, "TERMS", ["25"])

    term_ingest.refresh_term_data(force=True)

    with db.session_scope() as session:
        original = session.get(Opinion, original_id)
        revision = session.get(Opinion, revision_id)
        dissent = session.get(Opinion, dissent_id)
        assert original.author_name == "Thomas"
        assert original.separate_opinions == "Sotomayor (C/J)"
        assert original.has_dissent is False
        assert revision.author_name == "Thomas"
        assert revision.separate_opinions == "Sotomayor (C/J)"
        assert dissent.has_dissent is True
        assert dissent.separate_opinions == "Sotomayor (D)"
        assert dissent.author_name == "Barrett"


def test_failed_granted_list_fetch_does_not_cache_as_fresh(db, monkeypatch):
    from app import term_ingest

    def boom(term):
        raise RuntimeError("404 from supremecourt.gov")

    monkeypatch.setattr(term_ingest, "get_current_and_next_term", lambda: ("25", "26"))
    monkeypatch.setattr(term_ingest, "fetch_term_links", lambda: [])
    monkeypatch.setattr(term_ingest, "fetch_granted_noted_list", boom)
    monkeypatch.setattr(term_ingest, "fetch_and_parse_argument_calendars", lambda term: [])
    monkeypatch.setattr(term_ingest, "TERMS", ["25"])

    term_ingest.refresh_term_data(force=True)

    with db.session_scope() as session:
        row = session.get(TermSummary, "25")
        assert row is not None
        assert row.source_error
        assert "404" in row.source_error
        # Must still look stale so the next cycle retries.
        assert term_ingest._is_stale("25") is True


def test_refresh_covers_tracked_past_terms(db, monkeypatch):
    from app import term_ingest

    called = []

    def fake_fetch(term):
        called.append(term)
        return []

    monkeypatch.setattr(term_ingest, "get_current_and_next_term", lambda: ("25", "26"))
    monkeypatch.setattr(term_ingest, "fetch_term_links", lambda: [])
    monkeypatch.setattr(term_ingest, "fetch_granted_noted_list", fake_fetch)
    monkeypatch.setattr(term_ingest, "fetch_and_parse_argument_calendars", lambda term: [])
    monkeypatch.setattr(term_ingest, "TERMS", ["25", "24"])

    term_ingest.refresh_term_data(force=True)
    assert "24" in called
    assert "25" in called
    assert "26" in called
