from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


def uid():
    return str(uuid4())


class Word(Base):
    __tablename__ = "vocabulary_words"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    word: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    due: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    wrong: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Sense(Base):
    __tablename__ = "vocabulary_senses"
    __table_args__ = (UniqueConstraint("word_id", "pos", "meaning"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    word_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_words.id"), index=True)
    pos: Mapped[str] = mapped_column(String(40), default="")
    meaning: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)


class Alias(Base):
    __tablename__ = "vocabulary_aliases"
    __table_args__ = (UniqueConstraint("sense_id", "normalized"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    sense_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_senses.id"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)


class VocabularyImport(Base):
    __tablename__ = "vocabulary_imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    data: Mapped[dict] = mapped_column(JSON)
    confirmed: Mapped[bool] = mapped_column(default=False)


class VocabularySession(Base):
    __tablename__ = "vocabulary_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    day: Mapped[str] = mapped_column(String(10), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class SessionWord(Base):
    __tablename__ = "vocabulary_session_words"
    __table_args__ = (UniqueConstraint("session_id", "word_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_sessions.id"), index=True)
    word_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_words.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    data: Mapped[dict] = mapped_column(JSON)


class Attempt(Base):
    __tablename__ = "vocabulary_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_session_words.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(80), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
