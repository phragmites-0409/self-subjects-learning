"""Integration coverage for the confirmed bank, opt-in review and vocabulary rules."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import KnowledgeNode, Question
from app.modules.learning import service as flow
from app.modules.learning.models import LearningEvent, Occurrence, RoundItem
from app.modules.notifications import Delivery, maintain
from app.modules.vocabulary import service as vocab
from app.modules.vocabulary.models import Alias, Attempt, Sense, SessionWord, VocabularySession, Word


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(flow, "today", lambda: "2026-10-24")


def add_word(client, word="abandon", senses=None):
    response = client.post("/api/v1/vocabulary/words", json={"word": word, "senses": senses or [{"pos": "v.", "meaning": "放弃；抛弃"}]})
    assert response.status_code == 200, response.text
    return response.json()


def start(client):
    response = client.post("/api/v1/vocabulary/sessions/today")
    assert response.status_code == 200, response.text
    return response.json()


def answer(client, item, values, key="answer1"):
    response = client.post(f"/api/v1/vocabulary/items/{item['id']}/answer", json={"answers": values, "request_key": key})
    assert response.status_code == 200, response.text
    return response.json()


def test_bank_multileaf_multitag_counts_and_beyond_one_hundred(client, db, question_factory):
    parent = KnowledgeNode(subject="数学", kind="type", name="模型")
    db.add(parent); db.flush()
    nodes = [KnowledgeNode(subject="数学", kind="type", name=f"叶{i}", parent_id=parent.id) for i in range(3)]
    db.add_all(nodes); db.commit()
    for n in range(106):
        q, _ = question_factory(stem=f"题面{n}")
        state = flow.state_for(db, q.id); state.topic_id = nodes[n % 3].id
        q.tags_json = ["重点", "难题"] if n % 2 else ["重点"]
        db.commit()
    params = [("topic_ids", nodes[0].id), ("topic_ids", nodes[1].id), ("tags", "重点"), ("tags", "难题"), ("tag_mode", "all"), ("offset", 0), ("limit", 10)]
    result = client.get("/api/v1/learning/questions", params=params).json()
    assert result["total"] == 36 and len(result["items"]) == 10
    assert result["base_total"] == 71
    result = client.get("/api/v1/learning/questions", params={"offset": 100, "limit": 30}).json()
    assert result["total"] == 106 and len(result["items"]) == 6
    assert client.get("/api/v1/learning/questions", params={"topic_ids": parent.id}).status_code == 400
    assert client.get("/api/v1/learning/questions", params={"q": "题面105"}).json()["total"] == 1
    assert client.get("/api/v1/learning/questions", params={"q": "难题"}).json()["total"] == 53
    assert client.get("/api/v1/learning/questions", params={"date_from": "bad"}).status_code == 400


def test_default_type_off_and_pause_resume_keeps_in_progress(client, db, question_factory):
    node = KnowledgeNode(subject="数学", kind="type", name="方程"); db.add(node); db.flush()
    q, _ = question_factory(); state = flow.state_for(db, q.id)
    state.topic_id, state.ever_wrong, state.mastered = node.id, True, True
    db.commit()
    flow.activate_topics(db, flow.today())
    assert not flow.topic_state(db, node.id).active
    db.commit()
    assert client.post(f"/api/v1/learning/knowledge/{node.id}/review-switch", json={"enabled": True}).status_code == 200
    assert client.patch("/api/v1/learning/settings", json={"preferences": {"type_review_enabled": True}}).status_code == 200
    db.expire_all()
    assert flow.topic_state(db, node.id).active
    review = flow.make_round(db, "type", "数学", flow.today(), flow.today(), [state], node.id)
    event = flow.get_event(db, db.scalar(select(RoundItem).where(RoundItem.round_id == review.id)).event_id)
    db.commit()
    flow.save_preferences(db, {"type_review_enabled": False})
    assert event.status == "paused"
    assert flow.dashboard(db)["minutes"] == 0
    flow.save_preferences(db, {"type_review_enabled": True})
    assert event.status == "open"
    event.data = {**event.data, "started_day": flow.today()}; db.commit()
    flow.save_preferences(db, {"type_review_enabled": False})
    assert event.status == "open"


def test_word_import_preview_no_writes_and_idempotent_confirmation(client, db):
    preview = client.post("/api/v1/vocabulary/imports/preview", json={"text": "word | pos | meaning\nabandon | v. | 放弃\nabandon | n. | 放任\ninvalid", "source": "exam_3500"})
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert len(payload["items"]) == 2 and len(payload["errors"]) == 1
    assert db.scalar(select(func.count()).select_from(Word)) == 0
    first = client.post(f"/api/v1/vocabulary/imports/{payload['id']}/confirm").json()
    assert first == client.post(f"/api/v1/vocabulary/imports/{payload['id']}/confirm").json()
    assert first["created"] == 1 and first["merged"] == 1
    assert db.scalar(select(func.count()).select_from(Sense)) == 2
    add_word(client)
    db.expire_all()
    word = db.scalar(select(Word)); assert word.sources == ["daily", "exam_3500"]


def test_import_json_and_file_encoding(client):
    import json
    text = json.dumps([{"word": "ability", "pos": "n.", "meaning": "能力"}], ensure_ascii=False)
    preview = client.post("/api/v1/vocabulary/imports/file", files={"file": ("words.json", text.encode("gb18030"), "application/json")})
    assert preview.status_code == 200 and preview.json()["items"][0]["word"] == "ability"


def test_any_mode_synonym_pass_snapshot_idempotence_and_next_due(client, db):
    add_word(client)
    session = start(client); item = session["items"][0]
    assert item["senses"] == []
    assert start(client)["id"] == session["id"]
    result = answer(client, item, [" 抛弃！ "])
    assert result["status"] == "completed"
    assert answer(client, item, ["抛弃"], "answer1")["status"] == "completed"
    db.expire_all(); word = db.scalar(select(Word))
    assert word.due == "2026-10-25" and word.correct == 1
    assert db.scalar(select(func.count()).select_from(Attempt)) == 1


def test_all_mode_unordered_same_pos_uses_one_to_one_maximum_matching(client):
    client.patch("/api/v1/vocabulary/settings", json={"mode": "all"})
    add_word(client, "test", [{"pos": "v.", "meaning": "测验；检验"}, {"pos": "v.", "meaning": "测验"}, {"pos": "n.", "meaning": "测试"}])
    item = start(client)["items"][0]
    answers = ["测试" if t["pos"] == "n." else "测验" for t in item["targets"]]
    verb_slots = [n for n, t in enumerate(item["targets"]) if t["pos"] == "v."]
    answers[verb_slots[1]] = "检验"
    assert answer(client, item, answers)["status"] == "completed"


def test_all_mode_duplicate_meaning_does_not_cover_two_senses(client):
    client.patch("/api/v1/vocabulary/settings", json={"mode": "all"})
    add_word(client, "test", [{"pos": "v.", "meaning": "检查"}, {"pos": "v.", "meaning": "测验"}])
    result = answer(client, start(client)["items"][0], ["检查", "检查"])
    assert result["items"][0]["status"] == "review"


def test_manual_accept_alias_then_disable_preserves_standard(client, db):
    add_word(client)
    session = start(client); item = session["items"][0]
    result = answer(client, item, ["放下"])
    sid = result["items"][0]["senses"][0]["id"]
    result = client.post(f"/api/v1/vocabulary/items/{item['id']}/decision", json={"accepted": True, "corrections": [{"answer_index": 0, "sense_id": sid}]}).json()
    assert result["status"] == "completed"
    db.expire_all(); alias = db.scalar(select(Alias)); sense = db.get(Sense, sid)
    assert alias.normalized == "放下" and sense.meaning == "放弃；抛弃"
    assert client.patch(f"/api/v1/vocabulary/aliases/{alias.id}", json={"enabled": False}).status_code == 200
    assert client.delete(f"/api/v1/vocabulary/aliases/{alias.id}").status_code == 200


def test_wrong_same_session_retry_and_next_day_even_after_success(client, db):
    add_word(client)
    item = start(client)["items"][0]
    answer(client, item, ["错误"])
    result = client.post(f"/api/v1/vocabulary/items/{item['id']}/decision", json={"accepted": False}).json()
    assert result["items"][0]["status"] == "retry"
    assert answer(client, item, ["放弃"], "retry1")["status"] == "completed"
    db.expire_all(); word = db.scalar(select(Word))
    assert word.due == "2026-10-25" and word.wrong == 1 and word.stage == 0


def test_vocabulary_settings_frozen_and_all_review_stages(client, db):
    add_word(client)
    session = start(client)
    assert client.patch("/api/v1/vocabulary/settings", json={"daily_count": 5, "intervals": [2, 4]}).status_code == 200
    assert client.get(f"/api/v1/vocabulary/sessions/{session['id']}").json()["preferences"]["intervals"] == [1, 3, 7, 15, 30]
    answer(client, session["items"][0], ["放弃"])
    db.expire_all(); word = db.scalar(select(Word)); assert word.due == "2026-10-25"
    following = vocab.ensure_session(db, "2026-10-25", force=True)
    item = db.scalar(select(SessionWord).where(SessionWord.session_id == following.id))
    vocab.answer(db, item.id, ["放弃"], "next-day", "2026-10-25")
    assert word.due == "2026-10-29"
    following = vocab.ensure_session(db, "2026-10-29", force=True)
    item = db.scalar(select(SessionWord).where(SessionWord.session_id == following.id))
    vocab.answer(db, item.id, ["放弃"], "last-day", "2026-10-29")
    assert word.status == "mastered" and word.due is None


@pytest.mark.parametrize("body", [{"daily_count": 0}, {"daily_count": 1.5}, {"time": "25:00"}, {"intervals": []}, {"intervals": [True]}, {"mode": "unknown"}])
def test_invalid_vocabulary_preferences_rejected(client, body):
    assert client.patch("/api/v1/vocabulary/settings", json=body).status_code == 400


def test_overdue_items_consume_daily_quota_no_duplicates(client, db):
    client.patch("/api/v1/vocabulary/settings", json={"daily_count": 1})
    add_word(client); add_word(client, "ability", [{"pos": "n.", "meaning": "能力"}])
    first = start(client)
    assert vocab.ensure_session(db, "2026-10-25", force=True) is None
    assert db.scalar(select(func.count()).select_from(SessionWord)) == 1
    answer(client, first["items"][0], ["放弃"])
    new = vocab.ensure_session(db, "2026-10-25", force=True)
    assert new and len(vocab.session_view(db, new.id)["items"]) == 1


def test_notifications_before_time_and_restart_deduplication(client, db):
    add_word(client)
    sent = []
    maintain(db, day=flow.today(), clock="17:59", sender=lambda *args: sent.append(args))
    assert not sent
    maintain(db, day=flow.today(), clock="18:00", sender=lambda *args: sent.append(args))
    maintain(db, day=flow.today(), clock="19:00", sender=lambda *args: sent.append(args))
    assert len(sent) == 1
    receipt = db.scalar(select(Delivery)); assert receipt.status == "sent"
    assert db.scalar(select(func.count()).select_from(VocabularySession)) == 1


def test_desktop_notification_failure_is_visible_and_bounded(client, db):
    add_word(client)
    def fail(*args):
        raise RuntimeError("notifications disabled")
    for _ in range(4):
        maintain(db, day=flow.today(), clock="19:00", sender=fail)
    delivery = db.scalar(select(Delivery))
    assert delivery.attempts == 3 and delivery.status == "failed"
    assert "disabled" in client.get("/api/v1/learning/notifications").json()["deliveries"][0]["error"]


def test_paper_freezes_answer_and_history_copy_schedule_recovery(client, db, question_factory):
    q, _ = question_factory(stem="冻结题面")
    state = flow.state_for(db, q.id); state.answer = "FIRST_ANSWER"; state.answer_confirmed = True; db.commit()
    paper = client.post("/api/v1/papers", json={"title": "练习", "subject": "数学", "items": [{"question_id": q.id, "points": 6, "answer_space_mm": 40}]}).json()
    state.answer = "SECOND_ANSWER"; db.commit()
    revision = client.get(f"/api/v1/papers/{paper['id']}/revisions").json()
    assert revision["snapshot"]["items"][0]["data"]["answer"] == "FIRST_ANSWER"
    assert revision["snapshot"]["items"][0]["data"]["answer_space_mm"] == 40
    copied = client.post(f"/api/v1/papers/{paper['id']}/copy").json()
    assert client.get(f"/api/v1/papers/{copied['id']}/revisions").json()["snapshot"]["items"][0]["data"]["answer"] == "FIRST_ANSWER"
    review = client.post(f"/api/v1/papers/{paper['id']}/schedule", json={}).json()
    assert review["items"][0]["data"]["answer"] == "FIRST_ANSWER"
    assert client.post(f"/api/v1/papers/{paper['id']}/schedule", json={}).json()["id"] == review["id"]
    graded = client.patch(f"/api/v1/learning/items/{review['items'][0]['id']}", json={"verdict": "wrong"})
    assert graded.status_code == 200
    finished = client.post(f"/api/v1/learning/events/{review['events'][0]['id']}/action", json={"action": "finish"})
    assert finished.status_code == 200 and finished.json()["status"] == "completed"
    db.expire_all()
    occurrence = db.scalar(select(Occurrence).where(Occurrence.question_id == q.id))
    assert occurrence.target == "2026-10-31"


def test_vocab_photo_upload_does_not_create_question(client, db, png_bytes):
    result = client.post("/api/v1/assets", data={"purpose": "vocabulary"}, files={"file": ("words.png", png_bytes, "image/png")})
    assert result.status_code == 200 and result.json()["question_id"] is None
    assert db.scalar(select(func.count()).select_from(Question)) == 0


def test_word_task_abandon_releases_words_for_future_day(client, db):
    add_word(client); session = start(client)
    event = db.scalar(select(LearningEvent).where(LearningEvent.kind == "vocabulary"))
    assert client.post(f"/api/v1/learning/events/{event.id}/action", json={"action": "abandon"}).status_code == 200
    db.expire_all()
    assert db.get(VocabularySession, session["id"]).status == "abandoned"
    assert vocab.ensure_session(db, "2026-10-25", force=True)


def test_concurrent_session_creation_is_idempotent(client, db):
    add_word(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: client.post("/api/v1/vocabulary/sessions/today").json(), range(4)))
    assert len({r["id"] for r in results}) == 1
    assert db.scalar(select(func.count()).select_from(SessionWord)) == 1


def test_import_questions_preview_and_complete_draft_boundary(client, db):
    import json
    node = KnowledgeNode(subject="数学", kind="type", name="函数")
    db.add(node); db.commit()
    raw = [{"subject": "数学", "stem": "求x", "answer": "1", "topic_id": node.id}, {"subject": "数学", "stem": "待归类", "answer": "2"}, {"subject": "英语", "stem": "Translate", "answer": "译文"}, {"subject": "错误学科", "stem": "忽略"}]
    preview = client.post("/api/v1/question-bank/imports/preview", json={"text": json.dumps(raw)}).json()
    assert len(preview["items"]) == 3 and len(preview["errors"]) == 1
    assert db.scalar(select(func.count()).select_from(Question)) == 0
    result = client.post(f"/api/v1/question-bank/imports/{preview['id']}/confirm", json={"answers_confirmed": True}).json()
    assert result["approved"] == 2 and result["drafts"] == 1
    again = client.post(f"/api/v1/question-bank/imports/{preview['id']}/confirm", json={"answers_confirmed": True}).json()
    assert result == again
    assert client.get("/api/v1/learning/questions").json()["total"] == 2
    assert client.get("/api/v1/learning/questions", params={"filter": "draft"}).json()["total"] == 1


def test_pdf_math_falls_back_when_external_renderer_cache_unwritable(monkeypatch):
    from app.modules.learning.pdf import formatted
    from app.modules.learning import formula_rendering
    from app.storage.local_store import LocalFilesystemContentStore
    monkeypatch.setattr(formula_rendering, "ready", lambda: True)
    def unavailable(_):
        raise ValueError("cache unavailable")
    monkeypatch.setattr(formula_rendering, "render", unavailable)
    markup = formatted("$x^2+1$", LocalFilesystemContentStore())
    assert "<img " in markup and "$x" not in markup


def test_oversize_free_paper_does_not_enter_unbounded_splitting(client, db, question_factory):
    q, _ = question_factory()
    state = flow.state_for(db, q.id); state.minutes = 100; db.commit()
    paper = client.post("/api/v1/papers", json={"title": "超量卷", "subject": "数学", "items": [{"question_id": q.id}]}).json()
    response = client.post(f"/api/v1/papers/{paper['id']}/schedule", json={})
    assert response.status_code == 400


def test_paused_future_slice_does_not_close_in_progress_type_round(client, db, question_factory):
    node = KnowledgeNode(subject="数学", kind="type", name="方程")
    db.add(node); db.flush()
    topic = flow.topic_state(db, node.id); topic.data = {"review_enabled": True}
    flow.set_setting(db, "preferences", {**flow.preferences(db), "type_review_enabled": True})
    states = []
    for _ in range(3):
        q, _ = question_factory()
        state = flow.state_for(db, q.id); state.topic_id = node.id; state.minutes = 40
        states.append(state)
    review = flow.make_round(db, "type", "数学", flow.today(), flow.today(), states, node.id)
    flow.split_round(db, review, 90, 0, flow.today())
    events = db.scalars(select(LearningEvent).where(LearningEvent.data["round_id"].as_string() == review.id).order_by(LearningEvent.day)).all()
    first = events[0]; first.data = {**first.data, "started_day": flow.today()}; db.commit()
    flow.save_preferences(db, {"type_review_enabled": False})
    assert events[1].status == "paused"
    for item in db.scalars(select(RoundItem).where(RoundItem.event_id == first.id)):
        flow.record_item(db, item.id, {"verdict": "correct"})
    result = flow.finish_slice(db, first.id)
    assert result["status"] == "open"


def test_multiple_due_error_occurrences_share_one_redo_item(client, db, question_factory):
    q, _ = question_factory()
    flow.mark_error(db, q.id, "2026-10-10", "source:first")
    flow.mark_error(db, q.id, "2026-10-11", "source:second")
    db.commit()
    flow.plan(db)
    items = db.scalars(select(RoundItem).where(RoundItem.question_id == q.id)).all()
    assert len(items) == 1 and len(items[0].data["occurrences"]) == 2
    flow.mark_error(db, q.id, "2026-10-12", "source:third"); db.commit()
    flow.plan(db)
    assert db.scalar(select(func.count()).select_from(RoundItem)) == 1


def test_bank_date_range_uses_china_local_day(client, db, question_factory):
    from datetime import UTC, datetime
    q, _ = question_factory()
    q.created_at = datetime(2026, 10, 23, 17, tzinfo=UTC); db.commit()
    assert client.get("/api/v1/learning/questions", params={"date_from": "2026-10-24", "date_to": "2026-10-24"}).json()["total"] == 1
    assert client.get("/api/v1/learning/questions", params={"date_from": "2026-10-23", "date_to": "2026-10-23"}).json()["total"] == 0


def test_meaning_revision_does_not_attach_old_session_alias_to_new_meaning(client, db):
    word = add_word(client)
    item = start(client)["items"][0]
    result = answer(client, item, ["放下"])
    sid = result["items"][0]["senses"][0]["id"]
    assert client.patch(f"/api/v1/vocabulary/senses/{sid}", json={"meaning": "停止"}).status_code == 200
    decision = client.post(f"/api/v1/vocabulary/items/{item['id']}/decision", json={"accepted": True, "corrections": [{"answer_index": 0, "sense_id": sid}]})
    assert decision.status_code == 200 and decision.json()["status"] == "completed"
    assert db.scalar(select(func.count()).select_from(Alias)) == 0
