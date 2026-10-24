import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def now_utc() -> datetime:
    return datetime.now(UTC)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    subject: Mapped[str] = mapped_column(String(32), default="高中综合", index=True)
    grade: Mapped[str] = mapped_column(String(32), default="高中", index=True)
    question_type: Mapped[str] = mapped_column(String(128), default="待分类", index=True)
    difficulty: Mapped[str] = mapped_column(String(32), default="未知", index=True)
    methods_json: Mapped[list] = mapped_column(JSON, default=list)
    knowledge_points_json: Mapped[list] = mapped_column(JSON, default=list)
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, index=True)

    versions: Mapped[list["QuestionVersion"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    knowledge_links: Mapped[list["QuestionKnowledge"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    error_entries: Mapped[list["ErrorEntry"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class QuestionVersion(Base):
    __tablename__ = "question_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    content_storage_key: Mapped[str] = mapped_column(String(512))
    content_sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), default="ai")
    validation_status: Mapped[str] = mapped_column(String(32), default="valid")
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    question: Mapped[Question] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("question_id", "version_number"),)


class AIRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="deepseek")
    model: Mapped[str] = mapped_column(String(128), default="")
    policy_version: Mapped[str] = mapped_column(String(64), default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="题目讨论")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    question: Mapped[Question] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    client_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ai_run_id: Mapped[str | None] = mapped_column(ForeignKey("ai_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(32), default="高中综合")
    grade: Mapped[str] = mapped_column(String(32), default="高中")
    total_points: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    student_pdf_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    answer_pdf_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    items: Mapped[list["PaperItem"]] = relationship(back_populates="paper", cascade="all, delete-orphan", order_by="PaperItem.position")


class PaperItem(Base):
    __tablename__ = "paper_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    question_version_id: Mapped[str] = mapped_column(ForeignKey("question_versions.id"))
    position: Mapped[int] = mapped_column(Integer)
    points: Mapped[float] = mapped_column(Float, default=5)
    section_name: Mapped[str] = mapped_column(String(100), default="基础题")

    paper: Mapped[Paper] = relationship(back_populates="items")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    scopes_json: Mapped[list] = mapped_column(JSON, default=lambda: ["question:read", "question:write", "chat:write"])
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject: Mapped[str] = mapped_column(String(32), index=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)

    __table_args__ = (
        CheckConstraint(
            "subject IN ('数学', '物理', '化学', '生物', '语文', '英语')",
            name="ck_knowledge_nodes_supported_subject",
        ),
        CheckConstraint(
            "subject != '英语' OR kind IN ('composition_category', 'phrase', 'sentence_pattern', 'viewpoint', 'material', 'sample_excerpt')",
            name="ck_knowledge_nodes_english_composition_only",
        ),
    )

    parent: Mapped["KnowledgeNode | None"] = relationship(
        back_populates="children", remote_side="KnowledgeNode.id"
    )
    children: Mapped[list["KnowledgeNode"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    outgoing_edges: Mapped[list["KnowledgeEdge"]] = relationship(
        foreign_keys="KnowledgeEdge.source_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["KnowledgeEdge"]] = relationship(
        foreign_keys="KnowledgeEdge.target_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )
    contents: Mapped[list["KnowledgeContent"]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )
    question_links: Mapped[list["QuestionKnowledge"]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(32), index=True)

    source: Mapped[KnowledgeNode] = relationship(
        foreign_keys=[source_id], back_populates="outgoing_edges"
    )
    target: Mapped[KnowledgeNode] = relationship(
        foreign_keys=[target_id], back_populates="incoming_edges"
    )


class KnowledgeContent(Base):
    __tablename__ = "knowledge_contents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    content_storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    node: Mapped[KnowledgeNode] = relationship(back_populates="contents")


class QuestionKnowledge(Base):
    __tablename__ = "question_knowledge"

    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(String(32), default="tests")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(32), default="manual")

    question: Mapped[Question] = relationship(back_populates="knowledge_links")
    node: Mapped[KnowledgeNode] = relationship(back_populates="question_links")


class ErrorEntry(Base):
    __tablename__ = "error_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    added_date: Mapped[date] = mapped_column(Date, index=True)
    subject: Mapped[str] = mapped_column(String(32), index=True)
    question_type: Mapped[str] = mapped_column(String(128), index=True)
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    error_reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    note: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        CheckConstraint(
            "subject IN ('数学', '物理', '化学', '生物', '语文', '英语')",
            name="ck_error_entries_supported_subject",
        ),
    )

    question: Mapped[Question] = relationship(back_populates="error_entries")
    reviews: Mapped[list["ErrorReview"]] = relationship(
        back_populates="error_entry", cascade="all, delete-orphan", order_by="ErrorReview.reviewed_date"
    )


class ErrorReview(Base):
    __tablename__ = "error_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    error_entry_id: Mapped[str] = mapped_column(
        ForeignKey("error_entries.id", ondelete="CASCADE"), index=True
    )
    reviewed_date: Mapped[date] = mapped_column(Date, index=True)
    result: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")

    error_entry: Mapped[ErrorEntry] = relationship(back_populates="reviews")


_ENGLISH_COMPOSITION_KINDS = (
    "composition_category",
    "phrase",
    "sentence_pattern",
    "viewpoint",
    "material",
    "sample_excerpt",
)
_LEGACY_MIGRATION_VERSION = "english-knowledge-kind-v1"
_KNOWLEDGE_CHILD_TABLES = (
    "knowledge_edges",
    "knowledge_contents",
    "question_knowledge",
)


def _json_rows(result) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def _write_legacy_migration_report(report_path: str | Path | None, report: dict[str, Any]) -> None:
    if report_path is None:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _default_legacy_migration_report_path(bind) -> Path | None:
    """Return a durable report path for a file-backed SQLite database."""
    url = getattr(bind, "url", None)
    if url is None:
        url = getattr(getattr(bind, "engine", None), "url", None)
    database = getattr(url, "database", None)
    if not database or database == ":memory:":
        return None
    database_path = Path(database)
    data_dir = database_path.parent.parent if database_path.parent.name == "db" else database_path.parent
    return data_dir / "logs" / "english_knowledge_migration.json"


def _has_legacy_english_word_check(table_sql: str) -> bool:
    normalized = re.sub(r"\s+", " ", table_sql.lower())
    if "ck_knowledge_nodes_english_word_only" in normalized:
        return True
    # Cover unnamed/renamed checks such as ``kind IN ('word', 'phrase')``.
    return bool(
        re.search(r"subject\s*!=\s*'英语'.*kind\s*=\s*'word'", normalized)
        or re.search(r"subject\s*!=\s*'英语'.*kind\s+in\s*\([^)]*'word'", normalized)
    )


def migrate_legacy_english_knowledge_nodes(
    bind,
    *,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Replace the pre-Task-3A English-word CHECK in an existing SQLite DB.

    The migration is deliberately narrow and transactional. It snapshots every
    legacy English word row (and child rows that point at it) into a JSON report,
    copies all non-English and composition-kind nodes, and only then replaces the
    table. No vocabulary tables are assumed or created; Task 3B can consume the
    report later. A database that already has the new CHECK is a no-op.
    """

    if getattr(getattr(bind, "dialect", None), "name", None) != "sqlite":
        return {"status": "noop", "reason": "non_sqlite"}

    should_close = not hasattr(bind, "exec_driver_sql")
    connection = bind.connect() if should_close else bind
    effective_report_path = Path(report_path) if report_path is not None else _default_legacy_migration_report_path(bind)
    foreign_keys_enabled = True
    transaction = None
    try:
        foreign_keys_enabled = bool(connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
        table_sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_nodes'"
        ).scalar_one_or_none()
        if not table_sql:
            return {"status": "noop", "reason": "table_missing"}
        if not _has_legacy_english_word_check(table_sql):
            return {"status": "noop", "reason": "already_migrated"}

        # PRAGMA foreign_keys must be changed outside a transaction.
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        transaction = connection.begin()
        connection.exec_driver_sql("DROP TABLE IF EXISTS knowledge_nodes__task3a_new")
        all_rows = _json_rows(
            connection.execute(
                text(
                    "SELECT id, subject, parent_id, name, kind, summary, sort_order, status "
                    "FROM knowledge_nodes ORDER BY id"
                )
            )
        )
        composition_kinds = set(_ENGLISH_COMPOSITION_KINDS)
        legacy_word_rows = [
            row for row in all_rows if row["subject"] == "英语" and row["kind"] == "word"
        ]
        invalid_english_rows = [
            row for row in all_rows
            if row["subject"] == "英语" and row["kind"] not in composition_kinds and row["kind"] != "word"
        ]
        excluded_rows = legacy_word_rows + invalid_english_rows
        excluded_ids = {row["id"] for row in excluded_rows}
        retained_rows = [row for row in all_rows if row["id"] not in excluded_ids]
        retained_ids = {row["id"] for row in retained_rows}
        for row in retained_rows:
            if row["parent_id"] not in retained_ids:
                row["parent_id"] = None

        related_report: dict[str, list[dict[str, Any]]] = {}
        if excluded_ids:
            connection.exec_driver_sql(
                "CREATE TEMP TABLE task3a_legacy_ids (id VARCHAR(36) PRIMARY KEY)"
            )
            connection.execute(
                text("INSERT INTO task3a_legacy_ids (id) VALUES (:id)"),
                [{"id": value} for value in excluded_ids],
            )
            for table_name in _KNOWLEDGE_CHILD_TABLES:
                table_exists = connection.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
                    {"table_name": table_name},
                ).scalar_one_or_none()
                if not table_exists:
                    continue
                if table_name == "knowledge_edges":
                    related_report[table_name] = _json_rows(
                        connection.exec_driver_sql(
                            "SELECT * FROM knowledge_edges WHERE source_id IN "
                            "(SELECT id FROM task3a_legacy_ids) OR target_id IN "
                            "(SELECT id FROM task3a_legacy_ids)"
                        )
                    )
                    connection.exec_driver_sql(
                        "DELETE FROM knowledge_edges WHERE source_id IN "
                        "(SELECT id FROM task3a_legacy_ids) OR target_id IN "
                        "(SELECT id FROM task3a_legacy_ids)"
                    )
                else:
                    related_report[table_name] = _json_rows(
                        connection.exec_driver_sql(
                            f"SELECT * FROM {table_name} WHERE node_id IN "
                            "(SELECT id FROM task3a_legacy_ids)"
                        )
                    )
                    connection.exec_driver_sql(
                        f"DELETE FROM {table_name} WHERE node_id IN (SELECT id FROM task3a_legacy_ids)"
                    )
            connection.exec_driver_sql("DROP TABLE task3a_legacy_ids")

        composition_sql = ", ".join(f"'{kind}'" for kind in _ENGLISH_COMPOSITION_KINDS)
        connection.exec_driver_sql(
            f"""
            CREATE TABLE knowledge_nodes__task3a_new (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                subject VARCHAR(32) NOT NULL,
                parent_id VARCHAR(36),
                name VARCHAR(200) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL DEFAULT 'active',
                CONSTRAINT ck_knowledge_nodes_supported_subject
                    CHECK (subject IN ('数学', '物理', '化学', '生物', '语文', '英语')),
                CONSTRAINT ck_knowledge_nodes_english_composition_only
                    CHECK (subject != '英语' OR kind IN ({composition_sql})),
                CONSTRAINT fk_knowledge_nodes_parent
                    FOREIGN KEY(parent_id) REFERENCES knowledge_nodes__task3a_new(id) ON DELETE CASCADE
            )
            """
        )
        insert_sql = text(
            "INSERT INTO knowledge_nodes__task3a_new "
            "(id, subject, parent_id, name, kind, summary, sort_order, status) "
            "VALUES (:id, :subject, :parent_id, :name, :kind, :summary, :sort_order, :status)"
        )
        if retained_rows:
            connection.execute(insert_sql, retained_rows)
        connection.exec_driver_sql("DROP TABLE knowledge_nodes")
        connection.exec_driver_sql("ALTER TABLE knowledge_nodes__task3a_new RENAME TO knowledge_nodes")
        for index_name, column_name in (
            ("ix_knowledge_nodes_subject", "subject"),
            ("ix_knowledge_nodes_parent_id", "parent_id"),
            ("ix_knowledge_nodes_kind", "kind"),
            ("ix_knowledge_nodes_status", "status"),
        ):
            connection.exec_driver_sql(f"CREATE INDEX {index_name} ON knowledge_nodes ({column_name})")
        transaction.commit()
        transaction = None

        report = {
            "migration_version": _LEGACY_MIGRATION_VERSION,
            "status": "migrated",
            "legacy_word_count": len(legacy_word_rows),
            "invalid_english_count": len(invalid_english_rows),
            "retained_node_count": len(retained_rows),
            "legacy_word_rows": legacy_word_rows,
            "invalid_english_rows": invalid_english_rows,
            "legacy_related_rows": related_report,
        }
        _write_legacy_migration_report(effective_report_path, report)
        return report
    except Exception:
        if transaction is not None:
            transaction.rollback()
        raise
    finally:
        if connection.in_transaction():
            connection.rollback()
        connection.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")
        if should_close:
            connection.close()
