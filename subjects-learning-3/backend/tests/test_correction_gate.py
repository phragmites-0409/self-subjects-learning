"""Recording an error and confirming its correction are separate learning steps."""
import pytest
from sqlalchemy import select

from app.db.models import KnowledgeNode
from app.modules.learning import service as flow
from app.modules.learning.models import LearningEvent, Occurrence


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(flow, "today", lambda: "2026-10-24")


def record(client, qid, day="2026-10-24"):
    result = client.post(f"/api/v1/learning/questions/{qid}/error", json={"day": day})
    assert result.status_code == 200, result.text
    return result.json()


def test_new_intake_waits_for_correction_even_when_upload_date_is_old(client, db):
    node = client.post("/api/v1/learning/knowledge", json={"subject": "数学", "kind": "type", "name": "方程"}).json()
    q = client.post("/api/v1/learning/intake", json={"subject": "数学", "text": "求解 x+1=2", "is_error": True, "day": "2026-10-01"}).json()
    client.patch(f"/api/v1/learning/questions/{q['id']}", json={"topic_id": node["id"], "answer": "x=1"})
    result = client.post(f"/api/v1/learning/questions/{q['id']}/archive")
    assert result.status_code == 200, result.text
    assert result.json()["awaiting_correction"]
    assert result.json()["occurrences"][0]["target"] is None
    occurrence = db.scalar(select(Occurrence))
    assert occurrence.status == "awaiting_correction" and occurrence.target == ""
    flow.plan(db, "2026-11-01")
    assert not db.scalar(select(LearningEvent.id).where(LearningEvent.kind == "error"))
    result = client.post(f"/api/v1/learning/questions/{q['id']}/correct")
    assert result.status_code == 200 and not result.json()["awaiting_correction"]
    db.expire_all()
    assert occurrence.target == "2026-10-31" and occurrence.data["correction_day"] == "2026-10-24"


def test_confirmation_uses_current_interval_and_retries_do_not_restart_it(client, db, question_factory, monkeypatch):
    q, _ = question_factory()
    record(client, q.id, "2026-10-01")
    client.patch("/api/v1/learning/settings", json={"preferences": {"redo_days": 3}})
    assert client.post(f"/api/v1/learning/questions/{q.id}/correct").status_code == 200
    row = db.scalar(select(Occurrence))
    assert row.target == "2026-10-27"
    monkeypatch.setattr(flow, "today", lambda: "2026-10-25")
    client.patch("/api/v1/learning/settings", json={"preferences": {"redo_days": 9}})
    client.post(f"/api/v1/learning/questions/{q.id}/correct")
    db.expire_all()
    assert row.target == "2026-10-27" and row.data["redo_days"] == 3
    flow.plan(db, "2026-10-26")
    assert not db.scalar(select(LearningEvent.id).where(LearningEvent.kind == "error"))
    flow.plan(db, "2026-10-27")
    assert db.scalar(select(LearningEvent.id).where(LearningEvent.kind == "error"))


def test_waiting_errors_do_not_activate_type_rechecks_or_enter_ratio(client, db, question_factory):
    node = KnowledgeNode(subject="数学", kind="type", name="方程")
    db.add(node); db.flush()
    q, _ = question_factory()
    state = flow.state_for(db, q.id); state.topic_id = node.id
    topic = flow.topic_state(db, node.id)
    topic.data = {"review_enabled": True, "ever_active": True}
    flow.set_setting(db, "preferences", {"type_review_enabled": True})
    db.commit()
    record(client, q.id)
    db.expire_all()
    assert not topic.active and topic.target is None
    assert flow.topic_ratio(db, node.id)["total"] == 0
    client.post(f"/api/v1/learning/questions/{q.id}/correct")
    db.expire_all()
    assert topic.active and topic.target == "2026-11-08"
    assert flow.topic_ratio(db, node.id)["total"] == 1


def test_waiting_list_groups_subjects_deduplicates_questions_and_keeps_upload_completion(client, db, question_factory):
    q, _ = question_factory()
    record(client, q.id); record(client, q.id)
    record(client, q.id, "2026-10-23")
    physics, _ = question_factory(subject="物理"); record(client, physics.id)
    data = client.get("/api/v1/learning/corrections", params={"subject": "数学"}).json()
    assert data["total"] == 1 and data["counts"] == {"数学": 1, "物理": 1, "化学": 0, "生物": 0}
    assert data["items"][0]["occurrence_count"] == 2
    event = db.scalar(select(LearningEvent).where(LearningEvent.key == "upload:2026-10-24:数学"))
    assert client.post(f"/api/v1/learning/events/{event.id}/action", json={"action": "uploaded"}).status_code == 200
    assert client.post(f"/api/v1/learning/questions/{q.id}/correct").status_code == 200
    assert client.get("/api/v1/learning/corrections?subject=数学").json()["total"] == 0
    db.expire_all()
    assert all(o.target == "2026-10-31" for o in db.scalars(select(Occurrence).where(Occurrence.question_id == q.id)))
    assert event.status == "completed"


def test_waiting_list_paginates_and_rejects_non_stem_subjects(client, db, question_factory):
    for number in range(37):
        q, _ = question_factory(stem=f"待改错题{number}")
        flow.mark_error(db, q.id, flow.today(), f"test:{number}", awaiting_correction=True)
    db.commit()
    first = client.get("/api/v1/learning/corrections?limit=30").json()
    second = client.get("/api/v1/learning/corrections?offset=30&limit=30").json()
    assert first["total"] == 37 and len(first["items"]) == 30 and len(second["items"]) == 7
    assert not {q["question_id"] for q in first["items"]} & {q["question_id"] for q in second["items"]}
    assert client.get("/api/v1/learning/corrections?subject=英语").status_code == 400


def test_existing_retry_still_starts_next_day_without_a_second_correction_gate(client, db, question_factory):
    q, _ = question_factory()
    row = flow.mark_error(db, q.id, flow.today(), "retry:test", retry=True, target="2026-10-25")
    assert row.status == "pending" and row.target == "2026-10-25"
    assert not flow.question_view(db, q)["awaiting_correction"]
