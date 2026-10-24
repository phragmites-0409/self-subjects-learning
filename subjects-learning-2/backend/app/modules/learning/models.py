"""Local learning workflow. Existing question versions and source assets stay intact."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def new_id() -> str:
    return str(uuid4())


class AnswerDocument(Base):
    __tablename__ = "learning_answer_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    book: Mapped[str] = mapped_column(String(200))
    edition: Mapped[str] = mapped_column(String(100), default="")
    chapter: Mapped[str] = mapped_column(String(200), default="")
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AnswerPage(Base):
    __tablename__ = "learning_answer_pages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("learning_answer_documents.id"), index=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class QuestionState(Base):
    __tablename__ = "learning_question_states"
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id"), primary_key=True
    )
    topic_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=True
    )
    minutes: Mapped[float] = mapped_column(Float, default=8)
    answer: Mapped[str] = mapped_column(Text, default="")
    answer_confirmed: Mapped[bool] = mapped_column(default=False)
    ever_wrong: Mapped[bool] = mapped_column(default=False)
    mastered: Mapped[bool] = mapped_column(default=False)
    latest_correct: Mapped[bool | None] = mapped_column(nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class TopicState(Base):
    __tablename__ = "learning_topic_states"
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id"), primary_key=True
    )
    cadence: Mapped[int] = mapped_column(Integer, default=7)
    active: Mapped[bool] = mapped_column(default=False)
    target: Mapped[str | None] = mapped_column(String(10), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Occurrence(Base):
    __tablename__ = "learning_error_occurrences"
    __table_args__ = (UniqueConstraint("source_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    subject: Mapped[str] = mapped_column(String(20))
    upload_date: Mapped[str] = mapped_column(String(10), index=True)
    target: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    source_key: Mapped[str] = mapped_column(String(160), unique=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(20), default="")
    title: Mapped[str] = mapped_column(String(200))
    day: Mapped[str] = mapped_column(String(10), index=True)
    original_deadline: Mapped[str] = mapped_column(String(10))
    week: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    completed_day: Mapped[str | None] = mapped_column(String(10), nullable=True)
    minutes: Mapped[float] = mapped_column(Float, default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ReviewRound(Base):
    __tablename__ = "learning_rounds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(20))
    topic_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id"), nullable=True
    )
    target: Mapped[str] = mapped_column(String(10))
    day: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="open")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class RoundItem(Base):
    __tablename__ = "learning_round_items"
    __table_args__ = (UniqueConstraint("round_id", "question_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("question_versions.id"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(20), default="pending")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class WeeklyReport(Base):
    __tablename__ = "learning_weekly_reports"
    week: Mapped[str] = mapped_column(String(10), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
