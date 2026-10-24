import pytest
from sqlalchemy import select

from app.db.models import Question
from app.modules.learning import ai
from app.modules.learning import service as flow
from app.modules.learning.models import LearningEvent, Occurrence


def node(client, subject="物理", parent=None):
    return client.post("/api/v1/learning/knowledge", json={
        "subject": subject, "kind": "type", "name": "电场" if subject == "物理" else "方程", "parent_id": parent,
    }).json()["id"]


def plan_draft(client, context_subject="数学"):
    return client.post("/api/v1/learning/intake", json={
        "text": "电场中的带电粒子具有电势能", "is_error": True,
        "context": {"from": "plan", "subject": context_subject},
    }).json()


def complete_content(client, qid):
    assert client.patch(f"/api/v1/learning/questions/{qid}", json={"topic_id": node(client)}).status_code == 200
    assert client.post(f"/api/v1/learning/questions/{qid}/answer", json={"answer": "B"}).status_code == 200


def test_knowledge_selected_leaf_is_carried_into_matching_auto_subject(client):
    nid = node(client)
    q = client.post("/api/v1/learning/intake", json={
        "text": "电场中的带电粒子具有电势能", "is_error": False,
        "context": {"from": "knowledge", "subject": "物理", "branch": "type", "node_id": nid},
    }).json()
    assert q["subject"] == "物理" and q["topic_id"] == nid and q["question_type"] == "电场"
    assert q["data"]["subject_source"] == "auto"
    assert q["data"]["intake_context"]["node_id"] == nid


@pytest.mark.parametrize("parent,mismatch", [(True, False), (False, True)])
def test_knowledge_parent_or_different_subject_never_silently_assigns_type(client, parent, mismatch):
    subject = "数学" if mismatch else "物理"
    nid = node(client, subject)
    if parent:
        node(client, subject, nid)
    q = client.post("/api/v1/learning/intake", json={
        "text": "电场中的带电粒子具有电势能",
        "context": {"from": "knowledge", "subject": subject, "branch": "type", "node_id": nid},
    }).json()
    assert q["topic_id"] is None


def test_photo_recognition_carries_a_matching_user_selected_category(client, monkeypatch, png_bytes):
    nid = node(client)
    monkeypatch.setattr(ai, "recognition_available", lambda db: True)

    async def recognize(*args):
        return ai.Recognition(stem="电场中的带电粒子具有电势能", subject="物理")

    monkeypatch.setattr(ai, "recognize", recognize)
    uploaded = client.post("/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}).json()
    qid = uploaded["question_id"]
    client.post("/api/v1/learning/intake", json={"question_id": qid, "context": {
        "from": "knowledge", "subject": "物理", "branch": "type", "node_id": nid,
    }})
    q = client.get(f"/api/v1/learning/questions/{qid}").json()
    assert q["data"]["recognition"] == "completed" and q["topic_id"] == nid


def test_explicit_combined_archive_confirms_actual_subject_once(client, db):
    q = plan_draft(client, "数学")
    assert q["subject"] == "物理"
    complete_content(client, q["id"])
    for _ in range(2):
        result = client.post(f"/api/v1/learning/questions/{q['id']}/archive", json={"finish_daily": True})
        assert result.status_code == 200, result.text
        assert result.json()["data"]["daily_intake_completed"]
    db.expire_all()
    assert db.query(Occurrence).count() == 1
    day = q["data"]["intake_day"]
    events = {e.subject: e for e in db.scalars(select(LearningEvent).where(LearningEvent.kind == "upload", LearningEvent.day == day))}
    assert events["物理"].status == "completed" and events["物理"].data["outcome"] == "uploaded"
    assert events["数学"].status == "open" and events["化学"].status == "open" and events["生物"].status == "open"


def test_plain_archive_does_not_confirm_the_daily_upload(client, db):
    q = plan_draft(client)
    complete_content(client, q["id"])
    assert client.post(f"/api/v1/learning/questions/{q['id']}/archive").status_code == 200
    e = db.scalar(select(LearningEvent).where(LearningEvent.key == f"upload:{q['data']['intake_day']}:物理"))
    assert e.status == "open"


def test_missing_answer_or_changed_daily_event_leaves_intake_unpublished(client, db):
    q = plan_draft(client)
    client.patch(f"/api/v1/learning/questions/{q['id']}", json={"topic_id": node(client)})
    result = client.post(f"/api/v1/learning/questions/{q['id']}/archive", json={"finish_daily": True})
    assert result.status_code == 409
    db.expire_all()
    assert db.get(Question, q["id"]).status == "draft" and db.query(Occurrence).count() == 0
    client.post(f"/api/v1/learning/questions/{q['id']}/answer", json={"answer": "B"})
    e = db.scalar(select(LearningEvent).where(LearningEvent.key == f"upload:{q['data']['intake_day']}:物理"))
    e.status = "abandoned"; db.commit()
    result = client.post(f"/api/v1/learning/questions/{q['id']}/archive", json={"finish_daily": True})
    assert result.status_code == 409
    db.expire_all()
    assert db.get(Question, q["id"]).status == "draft" and db.query(Occurrence).count() == 0


def test_unrelated_intake_cannot_complete_daily_upload(client, db):
    q = client.post("/api/v1/learning/intake", json={"text": "电场中的带电粒子具有电势能", "is_error": True}).json()
    complete_content(client, q["id"])
    result = client.post(f"/api/v1/learning/questions/{q['id']}/archive", json={"finish_daily": True})
    assert result.status_code == 409 and "DAILY_INTAKE_MISMATCH" in result.text
    db.expire_all()
    assert db.get(Question, q["id"]).status == "draft" and db.query(Occurrence).count() == 0
