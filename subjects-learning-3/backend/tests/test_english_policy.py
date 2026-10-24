from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from app.ai.prompt_registry import PromptRegistry
from app.ai.schemas import (
    EnglishCompositionResult,
    VocabularyExtractResult,
    VocabularyLookupResult,
)
from app.db.models import KnowledgeNode, migrate_legacy_english_knowledge_nodes
from app.modules.knowledge.schemas import (
    ENGLISH_KNOWLEDGE_KINDS,
    KnowledgeNodeCreate,
)
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_ordinary_english_questions_are_solvable_by_the_solve_prompt():
    bundle = PromptRegistry().get("solve", "英语")

    assert "当前科目是英语" in bundle.system
    assert "阅读" in bundle.system
    assert "语法" in bundle.system
    assert "不得处理语法" not in bundle.system
    assert "仅处理单词" not in bundle.system
    assert "QuestionContentV1" in bundle.system


def test_english_task_prompts_are_allowlisted_and_isolated():
    registry = PromptRegistry()

    composition = registry.get("english_composition", "英语").system
    assert "EnglishCompositionResult" in composition
    assert "作文素材" in composition
    assert "用户确认" in composition
    assert "不得自动保存" in composition
    assert "grammar" not in composition.lower()

    extraction = registry.get("vocabulary_extract", "英语").system
    lookup = registry.get("vocabulary_lookup", "英语").system
    for prompt in (extraction, lookup):
        assert "单词" in prompt
        assert "不创建知识节点" in prompt
        assert "不自动保存" in prompt
        assert "语法" in prompt


def test_prompt_registry_rejects_unknown_task_and_keeps_task_files_allowlisted():
    registry = PromptRegistry()

    for task in ("english_composition", "vocabulary_extract", "vocabulary_lookup"):
        assert registry.get(task, "英文").system

    with pytest.raises(ValueError):
        registry.get("english_lookup", "英语")


def test_composition_schema_only_accepts_composition_knowledge_kinds():
    result = EnglishCompositionResult.model_validate(
        {
            "suggestions": [
                {
                    "kind": "phrase",
                    "content": "play an important role in",
                    "chinese_note": "在……中发挥重要作用",
                    "applicable_themes": ["社会发展"],
                }
            ]
        }
    )

    assert result.suggestions[0].kind == "phrase"
    assert set(ENGLISH_KNOWLEDGE_KINDS) == {
        "composition_category",
        "phrase",
        "sentence_pattern",
        "viewpoint",
        "material",
        "sample_excerpt",
    }
    with pytest.raises(ValidationError):
        EnglishCompositionResult.model_validate(
            {"suggestions": [{"kind": "grammar", "content": "present perfect"}]}
        )


def test_vocabulary_schemas_have_no_knowledge_node_output_or_persistence_contract():
    extracted = VocabularyExtractResult.model_validate(
        {"words": [{"word": "abandon", "context": "abandon the plan"}]}
    )
    looked_up = VocabularyLookupResult.model_validate(
        {
            "word": "abandon",
            "lemma": "abandon",
            "senses": [{"part_of_speech": "v.", "meaning": "放弃；抛弃"}],
        }
    )

    assert extracted.words[0].word == "abandon"
    assert looked_up.senses[0].meaning == "放弃；抛弃"
    assert not hasattr(extracted, "knowledge_nodes")
    assert not hasattr(looked_up, "knowledge_candidates")
    assert not hasattr(looked_up, "save")


def test_english_knowledge_schema_and_database_accept_only_composition_kinds(db):
    for kind in sorted(ENGLISH_KNOWLEDGE_KINDS):
        node = KnowledgeNodeCreate(subject="英语", name=f"素材-{kind}", kind=kind)
        assert node.kind == kind
        db.add(KnowledgeNode(subject=node.subject, name=node.name, kind=node.kind))
    db.commit()

    for kind in ("word", "grammar", "reading", "method"):
        with pytest.raises(ValidationError):
            KnowledgeNodeCreate(subject="英语", name=f"非法-{kind}", kind=kind)
        with pytest.raises(IntegrityError):
            db.add(KnowledgeNode(subject="英语", name=f"非法-{kind}", kind=kind))
            db.commit()
        db.rollback()


def test_legacy_english_word_migration_preserves_rows_reports_words_and_is_idempotent():
    with tempfile.TemporaryDirectory(prefix="task3a-migration-") as temp_dir:
        database_path = Path(temp_dir) / "legacy.sqlite3"
        report_path = Path(temp_dir) / "logs" / "english_knowledge_migration.json"
        engine = create_engine(f"sqlite:///{database_path}", future=True)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    CREATE TABLE knowledge_nodes (
                        id VARCHAR(36) PRIMARY KEY NOT NULL,
                        subject VARCHAR(32) NOT NULL,
                        parent_id VARCHAR(36),
                        name VARCHAR(200) NOT NULL,
                        kind VARCHAR(32) NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR(32) NOT NULL DEFAULT 'active',
                        CONSTRAINT ck_knowledge_nodes_supported_subject
                            CHECK (subject IN ('数学', '物理', '化学', '生物', '语文', '英语')),
                        CONSTRAINT ck_knowledge_nodes_english_word_only
                            CHECK (subject != '英语' OR kind = 'word')
                    )
                    """
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO knowledge_nodes
                            (id, subject, parent_id, name, kind, summary, sort_order, status)
                        VALUES (:id, :subject, NULL, :name, :kind, :summary, 0, 'active')
                        """
                    ),
                    [
                        {"id": "legacy-word", "subject": "英语", "name": "abandon", "kind": "word", "summary": "放弃"},
                        {"id": "math-node", "subject": "数学", "name": "函数", "kind": "point", "summary": "数学节点"},
                    ],
                )

            first = migrate_legacy_english_knowledge_nodes(engine, report_path=report_path)
            assert first["legacy_word_count"] == 1
            assert first["retained_node_count"] == 1
            with engine.connect() as connection:
                rows = connection.execute(text("SELECT id, subject, kind FROM knowledge_nodes ORDER BY id")).all()
                assert rows == [("math-node", "数学", "point")]
                schema_sql = connection.execute(
                    text("SELECT sql FROM sqlite_master WHERE type='table' AND name='knowledge_nodes'")
                ).scalar_one()
                assert "english_word_only" not in schema_sql

            assert json.loads(report_path.read_text(encoding="utf-8"))["legacy_word_rows"][0]["name"] == "abandon"
            second = migrate_legacy_english_knowledge_nodes(engine, report_path=report_path)
            assert second["status"] == "noop"
            with engine.connect() as connection:
                assert connection.execute(text("SELECT COUNT(*) FROM knowledge_nodes")).scalar_one() == 1
            assert json.loads(report_path.read_text(encoding="utf-8"))["legacy_word_count"] == 1
        finally:
            engine.dispose()


def test_migration_function_is_noop_for_non_sqlite_bind():
    class FakeDialect:
        name = "postgresql"

    class FakeBind:
        dialect = FakeDialect()

    assert migrate_legacy_english_knowledge_nodes(FakeBind())["status"] == "noop"


def test_current_knowledge_node_table_is_registered():
    # Keep this small assertion close to the migration tests so a future test
    # fixture change does not accidentally remove the table used by the policy.
    assert "knowledge_nodes" in KnowledgeNode.__table__.metadata.tables
