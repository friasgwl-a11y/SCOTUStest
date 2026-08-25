"""Regression tests for fetch durability.

The original implementation wrapped an entire fetch -- listing scrape plus
every PDF download -- in a single transaction, so any interruption during
PDF processing rolled back the listings too and left the database empty.
That is exactly what happens on a small/free hosting tier, where the
process can be OOM-killed or spun down mid-run. These tests pin down the
property that fixes it: whatever happens during document processing, the
scraped catalogue is already committed.
"""

import datetime as dt
from pathlib import Path

import pytest

from app import ingest, scraper

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A throwaway SQLite database wired into the app's session factory."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as db_module
    from app.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False))
    return db_module


@pytest.fixture(autouse=True)
def offline_scrape(monkeypatch):
    """Serve the listing pages from fixtures instead of the network."""
    def fake_get(url: str) -> str:
        name = "opinions_sample.html" if "opinions" in url else "orders_sample.html"
        return (FIXTURES / name).read_text(encoding="utf-8", errors="ignore")

    monkeypatch.setattr(scraper, "_get", fake_get)
    monkeypatch.setattr(scraper, "REQUEST_DELAY_SECONDS", 0)


def _counts(db):
    from app.models import Opinion, Order

    with db.session_scope() as session:
        return session.query(Opinion).count(), session.query(Order).count()


def test_listings_survive_document_processing_crash(db, monkeypatch):
    """An OOM-style crash during PDF processing must not lose the listings."""
    def boom(url):
        raise MemoryError("simulated OOM kill")

    monkeypatch.setattr(ingest, "fetch_and_extract", boom)
    ingest.run_fetch(terms=["25"], document_limit=3)

    opinions, orders = _counts(db)
    assert opinions == 76
    assert orders == 109


def test_total_document_failure_is_reported_as_error(db, monkeypatch):
    """Every document failing is systemic and must surface, not report success."""
    def blocked(url):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(ingest, "fetch_and_extract", blocked)
    result = ingest.run_fetch(terms=["25"], document_limit=2)

    assert result["status"] == "error"
    assert "document download(s) failed" in result["error"]
    assert "403 Forbidden" in result["error"]


def test_successful_documents_persist_despite_later_failures(db, monkeypatch):
    """Documents processed before a crash keep their extracted text."""
    from app.models import Opinion

    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] > 1:
            raise MemoryError("simulated OOM kill")
        return ("Extracted opinion text that is long enough to summarize properly.", 3)

    monkeypatch.setattr(ingest, "fetch_and_extract", flaky)
    ingest.run_fetch(terms=["25"], document_limit=4)

    with db.session_scope() as session:
        processed = session.query(Opinion).filter(Opinion.full_text.isnot(None)).count()
        errored = session.query(Opinion).filter(Opinion.extraction_error.isnot(None)).count()

    assert processed == 1
    assert errored >= 1


def test_rerun_resumes_and_does_not_duplicate(db, monkeypatch):
    """A second run re-uses stored listings instead of duplicating them."""
    monkeypatch.setattr(ingest, "fetch_and_extract", lambda url: ("text body here for summary", 1))

    first = ingest.run_fetch(terms=["25"], document_limit=1)
    assert first["new_opinions"] == 76

    second = ingest.run_fetch(terms=["25"], document_limit=1)
    assert second["new_opinions"] == 0
    assert second["new_orders"] == 0

    opinions, orders = _counts(db)
    assert opinions == 76
    assert orders == 109
