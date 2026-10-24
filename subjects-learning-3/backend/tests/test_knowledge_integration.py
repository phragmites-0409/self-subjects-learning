"""The approved tree prototype, backed by the real database and raw asset store."""
import base64
from copy import deepcopy
from hashlib import sha256

import pytest
from sqlalchemy import select

from app.db.models import Asset, KnowledgeNode, Question
from app.modules.learning import knowledge as kb, service as flow
from app.modules.learning.models import Occurrence, ReviewRound, RoundItem


def node(client, name="函数", parent=None, subject="数学", kind="type"):
    r = client.post("/api/v1/learning/knowledge", json={"name": name, "parent_id": parent, "subject": subject, "kind": kind})
    assert r.status_code == 200, r.text
    return r.json()


def get_node(client, nid):
    return next(n for n in client.get("/api/v1/learning/knowledge").json()["items"] if n["id"] == nid)


def save_entry(client, nid, payload, kind="note_entries", eid=None):
    path = f"/api/v1/learning/knowledge/{nid}/entries/{kind}"
    return client.patch(path + "/" + eid, json=payload) if eid else client.post(path, json=payload)


@pytest.mark.parametrize("subject,kind", [("数学", "type"), ("数学", "knowledge"), ("物理", "knowledge"), ("语文", "record"), ("英语", "record")])
def test_entries_are_independent_on_all_branches(client, subject, kind):
    n = node(client, subject=subject, kind=kind)
    a = save_entry(client, n["id"], {"title": "公式笔记", "body": "原文\n第二行", "tags": ["公式", "公式"], "pinned": True}).json()
    b = save_entry(client, n["id"], {"title": "我的困惑", "body": "条件限制"}, "pain_entries").json()
    assert a["tags"] == ["公式"] and b["images"] == []
    n = get_node(client, n["id"])
    assert n["data"]["note_entries"] == [a] and n["data"]["pain_entries"] == [b]
    updated = save_entry(client, n["id"], {**a, "body": "修订正文"}, eid=a["id"])
    assert updated.status_code == 200
    stale = save_entry(client, n["id"], {**a, "body": "过期修改"}, eid=a["id"])
    assert stale.status_code == 409
    assert get_node(client, n["id"])["data"]["note_entries"][0]["body"] == "修订正文"
    assert save_entry(client, n["id"], a, "pain_entries", a["id"]).status_code == 404


def test_legacy_fields_migrate_once_without_losing_contents(client, db):
    n = KnowledgeNode(subject="数学", kind="type", name="旧题型", summary="原正文")
    db.add(n); db.flush()
    flow.topic_state(db, n.id).data = {"method": "原方法", "notes": "原笔记", "pain_points": "原痛点", "tags": ["校外"]}
    db.commit()
    first = get_node(client, n.id)
    second = get_node(client, n.id)
    assert first["data"]["note_entries"] == second["data"]["note_entries"]
    assert [e["body"] for e in first["data"]["note_entries"]] == ["原正文", "原方法", "原笔记"]
    assert first["data"]["pain_entries"][0]["body"] == "原痛点"
    client.patch(f"/api/v1/learning/knowledge/{n.id}", json={"name": "新标题"})
    assert get_node(client, n.id)["data"] == first["data"]


def test_raw_upload_does_not_create_question_or_transform_original(client, db, png_bytes, monkeypatch):
    from app.modules.learning import ai
    monkeypatch.setattr(ai, "recognize", lambda *a, **k: pytest.fail("笔记原图不能调用识别"))
    before = db.query(Question).count()
    r = client.post("/api/v1/learning/knowledge-images", files={"file": ("课堂原图.png", png_bytes, "image/png")})
    assert r.status_code == 200
    image = r.json()
    assert image["size"] == len(png_bytes) and image["sha256"] == sha256(png_bytes).hexdigest()
    for suffix in ("", "?download=true&name=课堂原图.png"):
        download = client.get("/api/v1/learning/knowledge-images/" + image["id"] + suffix)
        assert download.content == png_bytes and download.headers["content-type"].startswith("image/png")
    assert db.query(Question).count() == before
    assert db.query(Asset).count() == 1
    n = node(client)
    e = save_entry(client, n["id"], {"title": "仅图片", "body": "", "images": [image], "pinned": True}).json()
    assert get_node(client, n["id"])["data"]["note_entries"][0] == e
    assert save_entry(client, n["id"], {**e, "images": []}, eid=e["id"]).status_code == 400
    assert client.post("/api/v1/learning/knowledge-images", files={"file": ("假图片.png", b"not an image", "image/png")}).status_code == 422


def test_tags_are_reusable_scoped_and_confirmation_is_enforced(client):
    n = node(client)
    assert save_entry(client, n["id"], {"title": "AI", "body": "内容", "source": "ai", "confirmed": False}).status_code == 400
    assert save_entry(client, n["id"], {"title": "AI", "body": "内容", "source": "ai", "confirmed": True, "tags": ["校外", "个人标签"], "tag_options": ["以后再用"]}).status_code == 200
    catalog = client.get("/api/v1/learning/knowledge-tags").json()
    assert "以后再用" in catalog["note"] and "个人标签" not in catalog["node"]
    assert get_node(client, n["id"])["data"]["tags"] == []
    assert client.patch(f"/api/v1/learning/knowledge/{n['id']}", json={"tags": ["校外"], "tag_options": ["分类标签"]}).status_code == 200
    assert "分类标签" in client.get("/api/v1/learning/knowledge-tags").json()["node"]


def test_create_before_reassignment_keeps_questions_and_history(client, db, question_factory):
    parent = node(client)
    q1, _ = question_factory(); q2, _ = question_factory(); draft, _ = question_factory(status="draft")
    for q in (q1, q2, draft):
        s = flow.state_for(db, q.id); s.topic_id = parent["id"]; s.ever_wrong = True; s.mastered = True
    db.commit()
    occurrence = flow.mark_error(db, q2.id, "2026-10-01", "saved-occurrence")
    db.commit()
    state = flow.state_for(db, q2.id)
    round_ = flow.make_round(db, "type", "数学", "2026-10-01", "2026-10-01", [state], parent["id"])
    db.commit()
    item = db.scalar(select(RoundItem).where(RoundItem.round_id == round_.id))
    item_snapshot = deepcopy(item.data)
    child = node(client, "具体情形", parent["id"])
    loaded = get_node(client, parent["id"])
    assert loaded["issue_count"] == 3 and loaded["mastery"]["total"] == 2
    assert client.get("/api/v1/learning/questions", params={"topic_id": parent["id"]}).json()["total"] == 2
    assert client.patch(f"/api/v1/learning/questions/{q2.id}", json={"topic_id": parent["id"], "tags": ["重点题"]}).status_code == 200
    assert client.patch(f"/api/v1/learning/questions/{q1.id}", json={"topic_id": child["id"]}).status_code == 200
    r = client.post(f"/api/v1/learning/knowledge/{parent['id']}/reassign", json={"assignments": {q2.id: child["id"]}})
    assert r.json()["remaining"] == 1
    db.expire_all()
    assert db.get(Occurrence, occurrence.id).source_key == "saved-occurrence"
    assert db.get(ReviewRound, round_.id).topic_id == parent["id"]
    assert db.get(RoundItem, item.id).data == item_snapshot
    assert db.query(Question).count() == 3
    r = client.post(f"/api/v1/learning/knowledge/{parent['id']}/reassign", json={"assignments": {draft.id: child["id"]}})
    assert r.json()["remaining"] == 0


def test_reassignment_failure_is_atomic_and_new_nonleaf_assignment_rejected(client, db, question_factory):
    p = node(client); other = node(client, "物理", subject="物理")
    qs = [question_factory()[0] for _ in range(2)]
    for q in qs:
        flow.state_for(db, q.id).topic_id = p["id"]
    db.commit()
    c = node(client, "子题型", p["id"])
    r = client.post(f"/api/v1/learning/knowledge/{p['id']}/reassign", json={"assignments": {qs[0].id: c["id"], qs[1].id: other["id"]}})
    assert r.status_code == 400
    assert get_node(client, p["id"])["issue_count"] == 2
    new, _ = question_factory()
    assert client.patch(f"/api/v1/learning/questions/{new.id}", json={"topic_id": p["id"]}).status_code == 400


def test_tag_facets_before_pagination_intersect_status_and_exact_labels(client, db, question_factory):
    p = node(client); k = node(client, "知识点", kind="knowledge")
    child = node(client, "具体知识点", k["id"], kind="knowledge")
    qs = [question_factory()[0] for _ in range(3)]
    for i, q in enumerate(qs):
        s = flow.state_for(db, q.id); s.topic_id = p["id"]; s.ever_wrong = i < 2; s.mastered = i == 0; s.data = {**s.data, "knowledge_ids": [k["id"], child["id"]]}; q.tags_json = ["模板题"] if i == 0 else ["难题", "含参数"] if i == 1 else []
    db.commit()
    result = client.get("/api/v1/learning/questions", params={"knowledge_id": k["id"], "limit": 1}).json()
    assert result["total"] == result["base_total"] == 3 and len(result["items"]) == 1
    assert result["untagged_total"] == 1 and {t["tag"]: t["count"] for t in result["tag_counts"]} == {"模板题": 1, "难题": 1, "含参数": 1}
    for f, expected in [("unmastered", 1), ("mastered", 0), ("ordinary", 0)]:
        result = client.get("/api/v1/learning/questions", params={"topic_id": p["id"], "filter": f, "tag": "难题"}).json()
        assert result["total"] == expected
    assert client.get("/api/v1/learning/questions", params={"tag": "模板"}).json()["total"] == 0
    assert client.get("/api/v1/learning/questions", params={"untagged": True}).json()["total"] == 1


def test_nonleaf_topics_never_activate_but_error_redo_survives(client, db, question_factory):
    p = node(client); q, _ = question_factory(); s = flow.state_for(db, q.id); s.topic_id = p["id"]; s.ever_wrong = s.mastered = True; db.commit()
    child = node(client, "新分支", p["id"])
    flow.activate_topics(db, "2026-10-23"); db.commit()
    assert not flow.topic_state(db, p["id"]).active
    occurrence = flow.mark_error(db, q.id, "2026-10-23", "nonleaf-error")
    db.commit()
    assert occurrence.status == "pending" and get_node(client, p["id"])["issue_count"] == 1
    assert child["data"]["tags"] == []


def test_knowledge_backup_roundtrip_with_originals_and_rejects_corruption(client, png_bytes):
    n = node(client)
    image = client.post("/api/v1/learning/knowledge-images", files={"file": ("原图.png", png_bytes, "image/png")}).json()
    e = save_entry(client, n["id"], {"title": "仅图", "body": "", "images": [image], "tags": ["公式"]}).json()
    backup = client.get("/api/v1/learning/knowledge-backup").json()
    assert base64.b64decode(backup["images"][0]["base64"]) == png_bytes
    assert client.post("/api/v1/learning/knowledge-backup", json=backup).status_code == 200
    new = get_node(client, n["id"])["data"]["note_entries"][0]
    assert new["id"] == e["id"] and new["revision"] == e["revision"] + 1
    assert client.get("/api/v1/learning/knowledge-images/" + new["images"][0]["id"]).content == png_bytes
    bad = deepcopy(backup); bad["nodes"][0]["name"] = "不该覆盖"; bad["images"][0]["base64"] = base64.b64encode(b"corrupt").decode()
    assert client.post("/api/v1/learning/knowledge-backup", json=bad).status_code == 400
    assert get_node(client, n["id"])["name"] == n["name"]
    missing = deepcopy(backup); missing["images"] = []
    assert client.post("/api/v1/learning/knowledge-backup", json=missing).status_code == 400
    assert get_node(client, n["id"])["data"]["note_entries"][0] == new


@pytest.mark.parametrize("subject,kind", [("英语", "knowledge"), ("英语", "type"), ("语文", "knowledge"), ("数学", "record")])
def test_subject_branch_boundaries(client, subject, kind):
    assert client.post("/api/v1/learning/knowledge", json={"name": "不匹配", "subject": subject, "kind": kind}).status_code == 400
