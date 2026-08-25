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
    # run_fetch also refreshes term-level data (current-term label, Granted
    # & Noted List, argument calendars) as a supplementary stage; that has
    # its own dedicated, offline tests in test_term_scraper.py, so it's
    # stubbed out here to keep these durability tests fast and hermetic.
    monkeypatch.setattr(ingest, "refresh_term_data", lambda *a, **k: None)
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
    monkeypatch.setattr(ingest, "AUTO_PROCESS_DAYS", 100000)
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
    # Widen the background window so this exercises multiple documents
    # regardless of how old the fixture's dates are relative to today.
    monkeypatch.setattr(ingest, "AUTO_PROCESS_DAYS", 100000)
    ingest.run_fetch(terms=["25"], document_limit=4)

    with db.session_scope() as session:
        processed = session.query(Opinion).filter(Opinion.full_text.isnot(None)).count()
        errored = session.query(Opinion).filter(Opinion.extraction_error.isnot(None)).count()

    assert processed == 1
    assert errored >= 1


def test_background_run_skips_older_documents(db, monkeypatch):
    """Only recently released documents are summarized in the background.

    This is what keeps memory bounded on a small instance: a fetch must
    not walk the whole back catalogue downloading PDFs.
    """
    processed_urls = []

    def record(url):
        processed_urls.append(url)
        return ("some extracted text for the summary", 2)

    monkeypatch.setattr(ingest, "fetch_and_extract", record)
    # Nothing in the fixtures is dated in the future, so a zero-day window
    # means every document is "too old" to process in the background.
    monkeypatch.setattr(ingest, "AUTO_PROCESS_DAYS", 0)
    ingest.run_fetch(terms=["25"], document_limit=10)

    assert processed_urls == []
    # ...but the catalogue is still fully populated.
    opinions, orders = _counts(db)
    assert opinions == 76 and orders == 109


def test_process_document_generates_summary_on_demand(db, monkeypatch):
    """Opening an unsummarized document produces its summary."""
    from app.models import Opinion

    monkeypatch.setattr(ingest, "AUTO_PROCESS_DAYS", 0)
    monkeypatch.setattr(
        ingest, "fetch_and_extract",
        lambda url: ("The Court holds that the statute is constitutional. "
                     "The judgment below is affirmed in full.", 5),
    )
    ingest.run_fetch(terms=["25"], document_limit=10)

    with db.session_scope() as session:
        target = session.query(Opinion).filter(Opinion.full_text.is_(None)).first()
        target_id = target.id
        assert target.summary is None

    result = ingest.process_document("opinion", target_id)

    assert result["summary"]
    assert result["page_count"] == 5
    with db.session_scope() as session:
        assert session.get(Opinion, target_id).full_text is not None


def test_process_document_is_idempotent(db, monkeypatch):
    """Re-opening a document doesn't re-download it."""
    from app.models import Opinion

    calls = {"n": 0}

    def counting(url):
        calls["n"] += 1
        return ("Extracted text used to build the summary for this case.", 1)

    monkeypatch.setattr(ingest, "AUTO_PROCESS_DAYS", 0)
    monkeypatch.setattr(ingest, "fetch_and_extract", counting)
    ingest.run_fetch(terms=["25"], document_limit=10)

    with db.session_scope() as session:
        target_id = session.query(Opinion).filter(Opinion.full_text.is_(None)).first().id

    ingest.process_document("opinion", target_id)
    ingest.process_document("opinion", target_id)
    ingest.process_document("opinion", target_id)

    assert calls["n"] == 1


def test_process_document_missing_id_returns_none(db):
    assert ingest.process_document("opinion", 999999) is None
    assert ingest.process_document("order", 999999) is None


def test_rerun_resumes_and_does_not_duplicate(db, monkeypatch):
    """A second run re-uses stored listings instead of duplicating them."""
    monkeypatch.setattr(ingest, "fetch_and_extract", lambda url: ("text body here for summary", 1))
    monkeypatch.setattr(ingest, "AUTO_PROCESS_DAYS", 0)

    first = ingest.run_fetch(terms=["25"], document_limit=1)
    assert first["new_opinions"] == 76

    second = ingest.run_fetch(terms=["25"], document_limit=1)
    assert second["new_opinions"] == 0
    assert second["new_orders"] == 0

    opinions, orders = _counts(db)
    assert opinions == 76
    assert orders == 109
