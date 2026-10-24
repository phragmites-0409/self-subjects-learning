from datetime import date

import pytest
from app.db.models import (
    ErrorEntry,
    ErrorReview,
    KnowledgeContent,
    KnowledgeEdge,
    KnowledgeNode,
    Question,
    QuestionKnowledge,
)
from app.modules.errors.schemas import ErrorEntryCreate, ErrorReviewCreate
from app.modules.knowledge.schemas import (
    KnowledgeContentCreate,
    KnowledgeNodeCreate,
    KnowledgeNodeUpdate,
)
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_domain_tables_are_initialized(db):
    table_names = set(inspect(db.bind).get_table_names())

    assert {
        "knowledge_nodes",
        "knowledge_edges",
        "knowledge_contents",
        "question_knowledge",
        "error_entries",
        "error_reviews",
    }.issubset(table_names)


def test_error_entry_stores_date_without_time_and_subject_is_restricted(db):
    question = Question(subject="数学", question_type="函数")
    entry = ErrorEntry(
        question=question,
        added_date=date(2026, 9, 2),
        subject="数学",
        question_type="函数",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    assert entry.added_date.isoformat() == "2026-09-02"
    assert entry.question_id == question.id
    assert entry.question is question


def test_error_entry_rejects_unknown_question_id(db):
    entry = ErrorEntry(
        question_id="missing-question",
        added_date=date(2026, 9, 2),
        subject="数学",
        question_type="函数",
    )
    db.add(entry)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()


def test_raw_question_delete_cascades_to_error_entries(db):
    question = Question(subject="数学", question_type="函数")
    entry = ErrorEntry(
        question=question,
        added_date=date(2026, 9, 2),
        subject="数学",
        question_type="函数",
    )
    db.add(entry)
    db.commit()
    entry_id = entry.id

    db.execute(text("DELETE FROM questions WHERE id = :question_id"), {"question_id": question.id})
    db.commit()
    db.expire_all()

    assert db.get(ErrorEntry, entry_id) is None


def test_english_knowledge_rejects_non_composition_kind():
    with pytest.raises(ValidationError):
        KnowledgeNodeCreate(subject="英语", name="时态", kind="grammar")


def test_knowledge_node_update_rejects_english_kind_only_patch():
    with pytest.raises(ValidationError):
        KnowledgeNodeUpdate(kind="grammar")


def test_knowledge_node_update_rejects_english_subject_only_patch():
    with pytest.raises(ValidationError):
        KnowledgeNodeUpdate(subject="英语")


def test_knowledge_node_update_merges_and_validates_current_state():
    update = KnowledgeNodeUpdate(name="新名称")

    assert update.merged_subject_kind(current_subject="英语", current_kind="phrase") == ("英语", "phrase")
    with pytest.raises(ValueError):
        update.merged_subject_kind(current_subject="英语", current_kind="grammar")


def test_schemas_restrict_subjects_and_english_to_composition_material(db):
    question = Question(subject="数学", question_type="函数")
    db.add(question)
    db.flush()

    with pytest.raises(ValidationError):
        KnowledgeNodeCreate(subject="历史", name="不支持", kind="chapter")
    with pytest.raises(ValidationError):
        ErrorEntryCreate(
            question_id=question.id,
            added_date=date(2026, 9, 2),
            subject="历史",
            question_type="阅读理解",
        )

    node = KnowledgeNodeCreate(subject="英语", name="make a difference", kind="phrase")
    assert node.subject == "英语"
    assert node.kind == "phrase"


def test_knowledge_and_question_relationships_cascade(db):
    question = Question(subject="数学", question_type="函数")
    parent = KnowledgeNode(subject="数学", name="函数", kind="chapter")
    child = KnowledgeNode(subject="数学", parent=parent, name="二次函数", kind="point")
    edge = KnowledgeEdge(source=parent, target=child, relation="contains")
    content = KnowledgeContent(node=child, title="二次函数", content_storage_key="structured-content/x", source="manual", content_hash="a" * 64)
    link = QuestionKnowledge(question=question, node=child, relation="tests", confidence=0.9, source="manual")
    db.add_all([question, parent, child, edge, content, link])
    db.commit()

    assert child.parent_id == parent.id
    assert child in parent.children
    assert edge.source_id == parent.id
    assert link.question_id == question.id

    db.delete(parent)
    db.commit()
    assert db.get(KnowledgeNode, child.id) is None
    assert db.get(KnowledgeEdge, edge.id) is None
    assert db.get(KnowledgeContent, content.id) is None
    assert db.get(QuestionKnowledge, (question.id, child.id)) is None


def test_error_review_cascades_with_error_entry(db):
    question = Question(subject="物理", question_type="选择题")
    entry = ErrorEntry(
        question=question,
        added_date=date(2026, 9, 2),
        subject="物理",
        question_type="选择题",
        tags_json=["受力"],
    )
    review = ErrorReview(error_entry=entry, reviewed_date=date(2026, 9, 3), result="mastered")
    db.add(review)
    db.commit()

    assert review.error_entry_id == entry.id
    db.delete(entry)
    db.commit()
    assert db.get(ErrorReview, review.id) is None


def test_raw_writes_reject_unsupported_subjects_and_english_grammar(db):
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO knowledge_nodes "
                "(id, subject, name, kind, summary, sort_order, status) "
                "VALUES (:id, :subject, :name, :kind, :summary, :sort_order, :status)"
            ),
            {
                "id": "invalid-subject",
                "subject": "历史",
                "name": "历史",
                "kind": "chapter",
                "summary": "",
                "sort_order": 0,
                "status": "active",
            },
        )
    db.rollback()

    with pytest.raises(IntegrityError):
        db.add(KnowledgeNode(subject="英语", name="时态", kind="grammar"))
        db.commit()
    db.rollback()


def test_raw_writes_reject_invalid_error_entry_subject(db):
    question = Question(subject="数学", question_type="函数")
    db.add(question)
    db.flush()

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO error_entries "
                "(id, question_id, added_date, subject, question_type, tags_json, error_reason, status, note) "
                "VALUES (:id, :question_id, :added_date, :subject, :question_type, :tags_json, :error_reason, :status, :note)"
            ),
            {
                "id": "invalid-error-subject",
                "question_id": question.id,
                "added_date": "2026-09-02",
                "subject": "历史",
                "question_type": "函数",
                "tags_json": "[]",
                "error_reason": "",
                "status": "open",
                "note": "",
            },
        )
    db.rollback()


def test_error_schemas_validate_required_fields_and_dates(db):
    question = Question(subject="语文", question_type="阅读理解")
    db.add(question)
    db.flush()

    entry = ErrorEntryCreate(
        question_id=question.id,
        added_date=date(2026, 9, 2),
        subject="语文",
        question_type="阅读理解",
    )
    review = ErrorReviewCreate(
        error_entry_id="e1",
        reviewed_date=date(2026, 9, 3),
        result="retry",
    )

    assert entry.subject == "语文"
    assert review.reviewed_date == date(2026, 9, 3)


def test_knowledge_content_schema_keeps_storage_reference_only():
    content = KnowledgeContentCreate(
        node_id="node-1",
        title="函数概念",
        content_storage_key="structured-content/ab/content.json",
        source="manual",
        content_hash="b" * 64,
    )

    assert content.content_storage_key.endswith("content.json")
    assert not hasattr(content, "content")
