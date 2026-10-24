"""Boundary scenarios: late work, corrected judgments, and failed AI do not erase evidence."""

import pytest
from app.db.models import KnowledgeNode, Question
from app.modules.learning import ai
from app.modules.learning import service as f
from app.modules.learning.models import (
    LearningEvent,
    Occurrence,
    ReviewRound,
    RoundItem,
    WeeklyReport,
)
from sqlalchemy import select


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(f, "today", lambda: "2026-10-05")


def prepared(db, factory, minutes=8):
    q, _ = factory()
    s = f.state_for(db, q.id)
    s.minutes = minutes
    db.commit()
    return q, s


def test_overdue_paper_participates_in_next_day_time_budget(
    db, question_factory, monkeypatch
):
    q, _s = prepared(db, question_factory, 60)
    o = f.mark_error(db, q.id, f.today(), "old", target=f.today())
    db.commit()
    f.plan(db)
    e = db.scalar(select(LearningEvent).where(LearningEvent.kind == "error"))
    q2, _ = prepared(db, question_factory, 40)
    f.mark_error(db, q2.id, "2026-10-06", "new", target="2026-10-06")
    db.commit()
    monkeypatch.setattr(f, "today", lambda: "2026-10-06")
    d = f.plan(db)
    assert d["minutes"] == 60 and e.day == "2026-10-06"
    assert (
        e.data["schedule_history"] == ["2026-10-05"]
        and o.data["round_id"] == e.data["round_id"]
    )
    assert db.query(ReviewRound).count() == 1 and d["pending_errors"] == 1


def test_correcting_false_type_error_keeps_audit_but_removes_wrong_state(
    db, question_factory
):
    n = KnowledgeNode(subject="数学", kind="type", name="验证题型")
    db.add(n)
    db.commit()
    q, s = prepared(db, question_factory)
    s.topic_id = n.id
    db.commit()
    r = f.make_round(db, "type", "数学", f.today(), f.today(), [s], n.id)
    db.commit()
    i = db.scalar(select(RoundItem).where(RoundItem.round_id == r.id))
    f.record_item(db, i.id, {"verdict": "wrong"})
    assert s.ever_wrong
    f.record_item(db, i.id, {"verdict": "correct"})
    assert not s.ever_wrong
    o = db.scalar(select(Occurrence).where(Occurrence.question_id == q.id))
    assert o.status == "corrected" and len(i.data["audit"]) == 2


def test_late_grading_seals_previous_week_before_mutating_event(
    client, db, question_factory, monkeypatch
):
    _q, s = prepared(db, question_factory)
    f.sync(db)
    r = f.make_round(db, "error", "数学", f.today(), f.today(), [s])
    db.commit()
    i = db.scalar(select(RoundItem).where(RoundItem.round_id == r.id))
    monkeypatch.setattr(f, "today", lambda: "2026-10-12")
    response = client.patch(
        f"/api/v1/learning/items/{i.id}", json={"verdict": "correct", "mastered": True}
    )
    assert response.status_code == 200
    report = db.get(WeeklyReport, "2026-10-05")
    original = next(
        e for e in report.data["events"] if e["data"].get("round_id") == r.id
    )
    assert original["status"] == "open" and report.data["carried"]


def test_question_can_change_subject_before_assignment_but_not_open_paper(
    client, db, question_factory
):
    q, s = prepared(db, question_factory)
    o = f.mark_error(db, q.id, f.today(), "manual")
    db.commit()
    assert (
        client.patch(
            f"/api/v1/learning/questions/{q.id}", json={"subject": "物理"}
        ).status_code
        == 200
    )
    db.refresh(o)
    assert o.subject == "物理"
    r = f.make_round(db, "error", "物理", f.today(), f.today(), [s])
    db.commit()
    assert r.subject == "物理"
    assert (
        client.patch(
            f"/api/v1/learning/questions/{q.id}", json={"subject": "数学"}
        ).status_code
        == 400
    )


def test_knowledge_parent_search_includes_attached_descendant_questions(
    client, db, question_factory
):
    parent = client.post(
        "/api/v1/learning/knowledge",
        json={"subject": "数学", "kind": "knowledge", "name": "代数"},
    ).json()
    child = client.post(
        "/api/v1/learning/knowledge",
        json={
            "subject": "数学",
            "kind": "knowledge",
            "name": "方程",
            "parent_id": parent["id"],
        },
    ).json()
    q, _ = prepared(db, question_factory)
    other, _ = prepared(db, question_factory)
    assert (
        client.patch(
            f"/api/v1/learning/questions/{q.id}", json={"knowledge_ids": [child["id"]]}
        ).status_code
        == 200
    )
    response = client.get(
        "/api/v1/learning/questions", params={"knowledge_id": parent["id"]}
    ).json()
    assert [row["id"] for row in response["items"]] == [q.id] and other.id != q.id


def test_ai_ocr_failure_keeps_archive_and_raw_source(
    client, db, png_bytes, monkeypatch
):
    client.patch(
        "/api/v1/learning/settings",
        json={"ai": {"key": "isolated-fake-key"}, "recognition": {"mode": "api"}},
    )

    async def failed(*args, **kwargs):
        raise RuntimeError("simulated vision failure")

    monkeypatch.setattr(ai, "recognize", failed)
    uploaded = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    response = client.post(
        "/api/v1/learning/intake",
        json={
            "question_id": uploaded["question_id"],
            "subject": "数学",
            "is_error": True,
        },
    )
    assert response.status_code == 200
    result = client.get(f"/api/v1/learning/questions/{uploaded['question_id']}").json()
    assert result["status"] == "draft" and result["data"]["recognition"] == "failed"
    assert result["content"]["stem"] == "" and not result["answer_confirmed"]
    assert (
        client.get(f"/api/v1/assets/{uploaded['asset_id']}/download").content
        == png_bytes
    )


def test_future_intake_is_rejected_before_creating_a_partial_record(client, db):
    response = client.post(
        "/api/v1/learning/intake",
        json={"text": "x=1", "is_error": True, "day": "2026-10-06"},
    )
    assert response.status_code == 400 and db.query(Question).count() == 0
