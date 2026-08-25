"""Regression tests for the REST API.

These specifically guard against a class of bug that bit two endpoints
during development: reading an ORM object's attributes *after* the
`session_scope()` block that loaded it has exited raises
DetachedInstanceError, because the session is already closed. Each fix
was to read the needed values while still inside the `with` block; these
tests hit the endpoints through a real TestClient so a regression shows up
as an HTTP 500, not just a passing unit test that never exercises the
route function's session lifecycle.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as db_module
    from app.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False))

    import app.main as main_module

    # The app's startup lifespan normally kicks off a real background
    # fetch against supremecourt.gov; that's exactly what these tests
    # must not do. Patching the module-level name (rather than relying on
    # an env var set before import) works regardless of whether app.main
    # was already imported by an earlier test.
    monkeypatch.setattr(main_module, "FETCH_ON_STARTUP", False)

    with TestClient(main_module.app) as test_client:
        yield test_client


def _seed_term_summary(term="25"):
    from app.db import session_scope
    from app.models import TermSummary

    with session_scope() as session:
        session.add(
            TermSummary(
                term=term,
                label="October Term 2025",
                is_current=True,
                total_granted=64,
                fetched_at=dt.datetime.utcnow(),
            )
        )


def _seed_question_presented(term="25"):
    from app.db import session_scope
    from app.models import QuestionPresented

    with session_scope() as session:
        session.add(
            QuestionPresented(
                term=term,
                docket="23-1197",
                case_name="LANDOR V. LA DEPT. OF CORRECTIONS",
                decision_below="82 F.4th 337",
                lower_court_case_number="22-30686",
                question_presented="Whether an individual may sue a government official.",
                status_line="CERT. GRANTED 6/23/2025",
            )
        )


def test_questions_presented_endpoint_returns_term_summary_and_items(client):
    _seed_term_summary()
    _seed_question_presented()

    resp = client.get("/api/questions-presented?term=25")
    assert resp.status_code == 200
    data = resp.json()
    assert data["term"] == "25"
    assert data["label"] == "October Term 2025"
    assert data["total_granted"] == 64
    assert len(data["items"]) == 1
    assert data["items"][0]["docket"] == "23-1197"


def test_questions_presented_endpoint_handles_unknown_term(client):
    resp = client.get("/api/questions-presented?term=99")
    assert resp.status_code == 200
    data = resp.json()
    assert data["label"] is None
    assert data["total_granted"] is None
    assert data["items"] == []


def test_term_summary_endpoint(client):
    _seed_term_summary()
    resp = client.get("/api/term-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_term"]["term"] == "25"


def test_argument_calendar_endpoint_empty(client):
    resp = client.get("/api/argument-calendar?days=1")
    assert resp.status_code == 200
    assert resp.json() == {"upcoming": []}
