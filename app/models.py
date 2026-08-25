import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Opinion(Base):
    __tablename__ = "opinions"
    __table_args__ = (UniqueConstraint("pdf_url", name="uq_opinion_pdf_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(8), index=True)
    rank: Mapped[str | None] = mapped_column(String(16), nullable=True)
    date: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)
    docket: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    case_name: Mapped[str] = mapped_column(String(512))
    justice: Mapped[str | None] = mapped_column(String(16), nullable=True)
    citation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_url: Mapped[str] = mapped_column(String(512))
    holding: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_revision: Mapped[bool] = mapped_column(default=False)

    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True when `summary` is the Reporter of Decisions' own syllabus
    # reproduced verbatim, rather than a generated summary (the fallback
    # for the rare opinion with no syllabus section).
    summary_is_syllabus: Mapped[bool] = mapped_column(default=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The following are populated from the Court's own Granted & Noted List
    # PDF (matched to this row by docket number), not from the opinion PDF
    # itself -- that document already states the majority author's full
    # name and, per case, exactly which other Justices concurred or
    # dissented (and how), which is far more reliable than trying to infer
    # it by pattern-matching the opinion text.
    granted_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    argument_date: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)
    author_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    separate_opinions: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_dissent: Mapped[bool] = mapped_column(default=False, index=True)

    first_seen_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )

    # Default (per-instance) lazy loading is fine here: this attribute is
    # only ever touched from to_dict(detail=True), which is used exclusively
    # by the single-opinion detail route, never the list endpoints.
    separate_opinion_texts: Mapped[list["SeparateOpinionText"]] = relationship(
        order_by="SeparateOpinionText.position",
        cascade="all, delete-orphan",
    )

    def to_dict(self, detail: bool = False) -> dict:
        d = {
            "id": self.id,
            "type": "opinion",
            "term": self.term,
            "rank": self.rank,
            "date": self.date.isoformat() if self.date else None,
            "docket": self.docket,
            "case_name": self.case_name,
            "justice": self.justice,
            "citation": self.citation,
            "pdf_url": self.pdf_url,
            "holding": self.holding,
            "is_revision": self.is_revision,
            "summary": self.summary,
            "summary_is_syllabus": self.summary_is_syllabus,
            "page_count": self.page_count,
            "has_full_text": bool(self.full_text),
            "extraction_error": self.extraction_error,
            "granted_date": self.granted_date.isoformat() if self.granted_date else None,
            "argument_date": self.argument_date.isoformat() if self.argument_date else None,
            "author_name": self.author_name,
            "separate_opinions": self.separate_opinions,
            "disposition": self.disposition,
            "has_dissent": self.has_dissent,
        }
        if detail:
            d["separate_opinion_texts"] = [s.to_dict() for s in self.separate_opinion_texts]
        return d


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("pdf_url", name="uq_order_pdf_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(8), index=True)
    date: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)
    order_type: Mapped[str] = mapped_column(String(64))
    pdf_url: Mapped[str] = mapped_column(String(512))

    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notable: Mapped[bool] = mapped_column(default=False)

    first_seen_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )

    def to_dict(self, detail: bool = False) -> dict:
        return {
            "id": self.id,
            "type": "order",
            "term": self.term,
            "date": self.date.isoformat() if self.date else None,
            "order_type": self.order_type,
            "pdf_url": self.pdf_url,
            "summary": self.summary,
            "page_count": self.page_count,
            "has_full_text": bool(self.full_text),
            "extraction_error": self.extraction_error,
            "notable": self.notable,
        }


class FetchRun(Base):
    __tablename__ = "fetch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    new_opinions: Mapped[int] = mapped_column(default=0)
    new_orders: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "new_opinions": self.new_opinions,
            "new_orders": self.new_orders,
            "error": self.error,
        }


class TermSummary(Base):
    """One row per term, refreshed from the Court's own site metadata and
    its Granted & Noted List PDF for that term."""

    __tablename__ = "term_summaries"

    term: Mapped[str] = mapped_column(String(8), primary_key=True)
    label: Mapped[str] = mapped_column(String(32))  # e.g. "October Term 2025"
    is_current: Mapped[bool] = mapped_column(default=False)
    total_granted: Mapped[int] = mapped_column(default=0)
    fetched_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    source_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "label": self.label,
            "is_current": self.is_current,
            "total_granted": self.total_granted,
            "fetched_at": self.fetched_at.isoformat(),
            "source_error": self.source_error,
        }


class ArgumentEntry(Base):
    """One row per case scheduled for oral argument on a given day, scraped
    from the Court's monthly Argument Calendar PDFs."""

    __tablename__ = "argument_entries"
    __table_args__ = (
        UniqueConstraint("term", "date", "docket", name="uq_argument_entry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(8), index=True)
    date: Mapped[dt.date] = mapped_column(index=True)
    docket: Mapped[str] = mapped_column(String(64))
    case_name: Mapped[str] = mapped_column(String(512))
    is_holiday: Mapped[bool] = mapped_column(default=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "date": self.date.isoformat(),
            "docket": self.docket,
            "case_name": self.case_name,
        }


class QuestionPresented(Base):
    """The legal question(s) the Court agreed to decide for one granted or
    noted case, scraped from the Court's own per-docket "Questions
    Presented" PDF (a stable URL built from the docket number, not a
    document listed in the Granted & Noted List itself)."""

    __tablename__ = "questions_presented"
    __table_args__ = (
        UniqueConstraint("term", "docket", name="uq_question_presented"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(8), index=True)
    docket: Mapped[str] = mapped_column(String(64))
    case_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decision_below: Mapped[str | None] = mapped_column(String(256), nullable=True)
    lower_court_case_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question_presented: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_line: Mapped[str | None] = mapped_column(String(128), nullable=True)
    not_available: Mapped[bool] = mapped_column(default=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "docket": self.docket,
            "case_name": self.case_name,
            "decision_below": self.decision_below,
            "lower_court_case_number": self.lower_court_case_number,
            "question_presented": self.question_presented,
            "status_line": self.status_line,
        }


class SeparateOpinionText(Base):
    """One concurrence or dissent, reproduced verbatim from the opinion
    PDF, located by author name using the Granted & Noted List's own
    concurrence/dissent breakdown (Opinion.separate_opinions) rather than
    by guessing at PDF heading text blindly. See
    app.summarizer.extract_separate_opinions."""

    __tablename__ = "separate_opinion_texts"
    __table_args__ = (
        UniqueConstraint("opinion_id", "position", name="uq_separate_opinion_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opinion_id: Mapped[int] = mapped_column(ForeignKey("opinions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # order of appearance in the PDF
    author: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)

    def to_dict(self) -> dict:
        return {
            "author": self.author,
            "code": self.code,
            "label": self.label,
            "text": self.text,
        }
