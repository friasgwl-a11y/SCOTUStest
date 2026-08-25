import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_seen_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )

    def to_dict(self, include_full_text: bool = False) -> dict:
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
            "page_count": self.page_count,
            "has_full_text": bool(self.full_text),
            "extraction_error": self.extraction_error,
        }
        if include_full_text:
            d["full_text"] = self.full_text
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

    def to_dict(self, include_full_text: bool = False) -> dict:
        d = {
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
        if include_full_text:
            d["full_text"] = self.full_text
        return d


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
