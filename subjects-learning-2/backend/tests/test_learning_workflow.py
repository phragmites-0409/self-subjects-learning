from io import BytesIO

import pytest
from app.core.errors import AppError
from app.db.models import Asset, KnowledgeNode, Question
from app.modules.learning import ai
from app.modules.learning import service as f
from app.modules.learning.models import (
    LearningEvent,
    Occurrence,
    ReviewRound,
    RoundItem,
    WeeklyReport,
)
from app.modules.learning.pdf import export_pdf
from app.storage.local_store import LocalFilesystemContentStore
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(f, "today", lambda: "2026-10-05")


def topic(db, subject="数学", **data):
    n = KnowledgeNode(subject=subject, kind="type", name="方程")
    db.add(n)
    db.flush()
    s = f.topic_state(db, n.id)
    s.data = {"review_enabled": True, **data}
    f.set_setting(db, "preferences", {**f.preferences(db), "type_review_enabled": True})
    db.commit()
    return n, s


def qstate(db, factory, tid=None, **kwargs):
    q, _v = factory(subject=kwargs.pop("subject", "数学"))
    s = f.state_for(db, q.id)
    s.topic_id = tid
    for k, val in kwargs.items():
        setattr(s, k, val)
    db.commit()
    return q, s


def round_items(db, r):
    return db.scalars(
        select(RoundItem).where(RoundItem.round_id == r.id).order_by(RoundItem.position)
    ).all()


def round_event(db, r):
    return db.scalar(
        select(LearningEvent).where(LearningEvent.key == f"round:{r.id}:1")
    )


def test_intake_saves_draft_without_analysis_or_fake_answer(client, db, png_bytes):
    uploaded = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    result = client.post(
        "/api/v1/learning/intake",
        json={
            "question_id": uploaded["question_id"],
            "subject": "物理",
            "is_error": True,
        },
    )
    assert result.status_code == 200, result.text
    q = result.json()
    assert q["status"] == "draft" and q["content"]["stem"] == ""
    assert q["answer"] == "" and not q["answer_confirmed"]
    assert "analysis" not in q["data"]
    assert (
        LocalFilesystemContentStore().read_bytes(
            db.get(Asset, uploaded["asset_id"]).storage_key
        )
        == png_bytes
    )
    assert q["occurrences"] == [] and q["data"]["pending_error"]
    again = client.post(
        "/api/v1/learning/intake",
        json={"question_id": q["id"], "subject": "物理", "is_error": True},
    )
    assert again.status_code == 200 and db.query(Occurrence).count() == 0


def test_crop_is_lossless_derivative_with_original_history(client, db, png_bytes):
    uploaded = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    client.post(
        "/api/v1/learning/intake", json={"question_id": uploaded["question_id"]}
    )
    cropped = client.post(
        f"/api/v1/learning/questions/{uploaded['question_id']}/crop",
        json={"left": 0.25, "top": 0.25, "right": 0.75, "bottom": 0.75},
    )
    assert cropped.status_code == 200
    aid = cropped.json()["data"]["crop_asset_id"]
    im = Image.open(BytesIO(client.get(f"/api/v1/assets/{aid}/download").content))
    original = Image.open(BytesIO(png_bytes))
    assert im.size == (40, 20) and im.getpixel((0, 0)) == original.getpixel((20, 10))
    assert (
        client.get(f"/api/v1/assets/{uploaded['asset_id']}/download").content
        == png_bytes
    )
    assert len(cropped.json()["data"]["crop_history"]) == 1


def test_daily_four_events_are_idempotent_and_no_errors_is_explicit(db):
    f.sync(db)
    f.sync(db)
    uploads = db.scalars(
        select(LearningEvent).where(LearningEvent.kind == "upload")
    ).all()
    assert len(uploads) == 4 and all(e.status == "open" for e in uploads)
    f.finish_upload(db, uploads[0].id, True)
    assert (
        uploads[0].status == "completed" and uploads[0].data["outcome"] == "no_errors"
    )
    with pytest.raises(AppError):
        f.finish_upload(db, uploads[1].id, False)


def test_day_clear_is_independent_from_unmastered_errors(db, question_factory):
    f.sync(db)
    q, s = qstate(db, question_factory)
    f.mark_error(db, q.id, f.today(), "test-upload")
    db.commit()
    e = db.scalar(
        select(LearningEvent).where(
            LearningEvent.subject == "数学", LearningEvent.kind == "upload"
        )
    )
    with pytest.raises(AppError):
        f.finish_upload(db, e.id, True)
    f.finish_upload(db, e.id, False)
    assert e.status == "completed" and not s.mastered
    assert db.query(ReviewRound).count() == 0


def test_week_report_carries_identity_and_is_immutable_after_late_completion(db):
    f.sync(db)
    e = db.scalar(select(LearningEvent).where(LearningEvent.subject == "数学"))
    eid, deadline = e.id, e.original_deadline
    f.sync(db, "2026-10-12")
    first = db.get(WeeklyReport, "2026-10-05")
    assert len(first.data["events"]) == 28
    assert (
        eid in first.data["carried"]
        and e.week == "2026-10-12"
        and e.original_deadline == deadline
    )
    f.finish_upload(db, eid, True, "2026-10-12")
    assert next(x for x in first.data["events"] if x["id"] == eid)["status"] == "open"
    f.sync(db, "2026-10-19")
    assert (
        next(
            x
            for x in db.get(WeeklyReport, "2026-10-12").data["events"]
            if x["id"] == eid
        )["status"]
        == "completed"
    )


def test_abandon_is_separate_from_complete_and_report_keeps_reason(db):
    f.sync(db)
    e = db.scalar(select(LearningEvent).where(LearningEvent.subject == "数学"))
    f.abandon_event(db, e.id, "无法补齐原件")
    f.sync(db, "2026-10-12")
    report = db.get(WeeklyReport, "2026-10-05").data
    assert e.id in [x["id"] for x in report["abandoned"]]
    assert e.id not in report["carried"]
    assert report["abandoned"][0]["data"]["abandon_reason"] == "无法补齐原件"


def test_initial_error_redo_seven_days_correct_needs_manual_mastery(
    db, question_factory
):
    q, s = qstate(db, question_factory)
    f.mark_error(db, q.id, f.today(), "initial")
    db.commit()
    f.plan(db, "2026-10-11")
    assert db.query(ReviewRound).count() == 0
    f.plan(db, "2026-10-12")
    r = db.query(ReviewRound).one()
    i = round_items(db, r)[0]
    e = round_event(db, r)
    f.record_item(db, i.id, {"verdict": "correct"}, "2026-10-12")
    assert not s.mastered and i.status == "judged"
    with pytest.raises(AppError):
        f.finish_slice(db, e.id, "2026-10-12")
    f.record_item(db, i.id, {"verdict": "correct", "mastered": True}, "2026-10-12")
    f.finish_slice(db, e.id, "2026-10-12")
    assert s.mastered and r.status == "completed" and db.query(Occurrence).count() == 1


def test_wrong_retry_counts_from_learned_click_and_new_round(db, question_factory):
    q, _s = qstate(db, question_factory)
    f.mark_error(db, q.id, f.today(), "initial")
    db.commit()
    f.plan(db, "2026-10-12")
    r = db.query(ReviewRound).one()
    i = round_items(db, r)[0]
    e = round_event(db, r)
    f.record_item(
        db, i.id, {"verdict": "wrong", "explanation": "应为x=1"}, "2026-10-12"
    )
    assert db.query(Occurrence).count() == 1 and i.status == "judged"
    f.record_item(
        db,
        i.id,
        {"verdict": "wrong", "explanation": "应为x=1", "learned": True},
        "2026-10-14",
    )
    retry = db.scalar(select(Occurrence).where(Occurrence.source_key.like("retry:%")))
    assert retry.target == "2026-10-15"
    f.finish_slice(db, e.id, "2026-10-14")
    f.plan(db, "2026-10-15")
    assert db.query(ReviewRound).count() == 2 and r.status == "completed"
    assert (
        len(
            {
                x.id
                for x in db.query(LearningEvent).filter(LearningEvent.kind == "error")
            }
        )
        == 2
    )


def test_correct_but_not_mastered_retries_next_day_and_uncertain_blocks(
    db, question_factory
):
    q, s = qstate(db, question_factory)
    o = f.mark_error(db, q.id, f.today(), "initial")
    db.commit()
    r = f.make_round(db, "error", "数学", o.target, f.today(), [s], occurrences=[o])
    db.commit()
    i = round_items(db, r)[0]
    f.record_item(db, i.id, {"verdict": "uncertain"})
    with pytest.raises(AppError):
        f.finish_slice(db, round_event(db, r).id)
    f.record_item(db, i.id, {"verdict": "correct", "mastered": False})
    assert (
        db.scalar(
            select(Occurrence).where(Occurrence.source_key.like("retry:%"))
        ).target
        == "2026-10-06"
    )
    assert not s.mastered


def test_manual_rejudgment_before_close_retracts_unissued_retry(db, question_factory):
    q, s = qstate(db, question_factory)
    o = f.mark_error(db, q.id, f.today(), "initial")
    db.commit()
    r = f.make_round(db, "error", "数学", o.target, f.today(), [s], occurrences=[o])
    db.commit()
    i = round_items(db, r)[0]
    f.record_item(
        db, i.id, {"verdict": "wrong", "learned": True, "explanation": "原先判断有误"}
    )
    assert db.query(Occurrence).count() == 2
    f.record_item(db, i.id, {"verdict": "correct", "mastered": True})
    assert db.query(Occurrence).count() == 1 and s.mastered


def test_mastery_threshold_uses_unique_historical_questions_not_occurrences(
    db, question_factory
):
    n, ts = topic(db)
    for index in range(5):
        q, _s = qstate(db, question_factory, n.id, ever_wrong=True, mastered=index < 4)
        for occurrence in range(3):
            db.add(
                Occurrence(
                    question_id=q.id,
                    subject="数学",
                    upload_date=f.today(),
                    target="2026-10-12",
                    source_key=f"{q.id}-{occurrence}",
                )
            )
    db.commit()
    f.activate_topics(db, f.today())
    db.commit()
    assert f.topic_ratio(db, n.id) == {"total": 5, "mastered": 4, "ratio": 80.0}
    assert ts.active and ts.cadence == 7 and ts.target == "2026-10-12"


def test_zero_historical_errors_does_not_auto_activate(db, question_factory):
    n, ts = topic(db)
    qstate(db, question_factory, n.id)
    f.activate_topics(db, f.today())
    assert not ts.active and f.topic_ratio(db, n.id)["ratio"] is None


def test_type_pool_excludes_unmastered_and_entire_previous_round(db, question_factory):
    n, _ts = topic(db)
    _q1, s1 = qstate(db, question_factory, n.id)
    _q2, s2 = qstate(db, question_factory, n.id)
    _q3, _s3 = qstate(db, question_factory, n.id, ever_wrong=True, mastered=False)
    f.make_round(db, "type", "数学", f.today(), f.today(), [s1, s2], n.id)
    db.commit()
    assert f.eligible(db, n.id) == []
    q4, _s4 = qstate(db, question_factory, n.id)
    assert [s.question_id for s in f.eligible(db, n.id)] == [q4.id]


def test_sampling_tags_and_latest_correctness_have_equal_influence(
    db, question_factory
):
    q, s = qstate(db, question_factory, latest_correct=False)
    assert f.sampling_weight(s, q) == 4
    s.latest_correct = True
    q.tags_json = ["重点题"]
    assert f.sampling_weight(s, q) == 3.5
    q.tags_json = []
    assert f.sampling_weight(s, q) == 1.5


def type_round(db, factory, n, ts, day, wrong=False, passed=True, special=False):
    q, s = qstate(db, factory, n.id)
    r = f.make_round(db, "type", n.subject, day, day, [s], n.id, special=special)
    db.commit()
    f.sync(db, day)
    i = round_items(db, r)[0]
    f.record_item(db, i.id, {"verdict": "wrong" if wrong else "correct"}, day)
    f.finish_slice(db, round_event(db, r).id, day, passed)
    return r, q, s


def test_all_correct_manual_fail_preserves_streak_but_prevents_downgrade(
    db, question_factory
):
    n, ts = topic(db, ever_active=True, correct_streak=1)
    ts.active = True
    ts.cadence = 7
    db.commit()
    r, _, _ = type_round(db, question_factory, n, ts, f.today(), passed=False)
    assert ts.cadence == 7 and ts.data["correct_streak"] == 2 and not r.data["passed"]
    type_round(db, question_factory, n, ts, "2026-10-13", passed=True)
    assert ts.cadence == 15 and ts.data["correct_streak"] == 0


def test_type_wrong_is_today_error_suspect_no_pause_and_auto_fail(db, question_factory):
    n, ts = topic(db, ever_active=True)
    ts.active = True
    db.commit()
    r, q, s = type_round(
        db, question_factory, n, ts, f.today(), wrong=True, passed=True
    )
    o = db.scalar(select(Occurrence).where(Occurrence.question_id == q.id))
    assert o.upload_date == f.today() and o.target == "2026-10-12"
    assert ts.active and ts.data["suspect"] and not r.data["passed"] and not s.mastered
    assert ts.target == "2026-10-12"


def test_frequency_only_three_seven_fifteen_and_manual_stop(db, question_factory):
    n, ts = topic(db, ever_active=True)
    ts.active = True
    ts.cadence = 3
    db.commit()
    for d in ("2026-10-05", "2026-10-06"):
        type_round(db, question_factory, n, ts, d)
    assert ts.cadence == 7
    for d in ("2026-10-07", "2026-10-08"):
        type_round(db, question_factory, n, ts, d)
    assert ts.cadence == 15
    for d in ("2026-10-09", "2026-10-10"):
        type_round(db, question_factory, n, ts, d)
    assert ts.active and ts.data["stop_pending"]
    f.confirm_stop(db, n.id, True)
    assert not ts.active and ts.target is None
    q, _s = qstate(db, question_factory, n.id)
    f.mark_error(db, q.id, "2026-10-11", "new-one")
    db.commit()
    assert ts.active and ts.cadence == 15 and ts.target == "2026-10-26"
    f.mark_error(db, q.id, "2026-10-12", "new-two")
    db.commit()
    assert ts.target == "2026-10-26"
    r, _, _ = type_round(
        db, question_factory, n, ts, "2026-10-26", passed=False, special=True
    )
    assert not ts.active and r.data["automatic_stop"]


def test_continuous_wrong_increases_frequency_and_pass_clears_suspect(
    db, question_factory
):
    n, ts = topic(db, ever_active=True)
    ts.active = True
    ts.cadence = 15
    db.commit()
    for d in ("2026-10-05", "2026-10-06"):
        type_round(db, question_factory, n, ts, d, wrong=True)
    assert ts.cadence == 7
    for d in ("2026-10-07", "2026-10-08"):
        type_round(db, question_factory, n, ts, d, wrong=True)
    assert ts.cadence == 3
    type_round(db, question_factory, n, ts, "2026-10-09", passed=True)
    assert not ts.data["suspect"]


def test_outside_tag_and_small_pool_produce_no_push(db, question_factory):
    n, ts = topic(db, tags=["校外"], ever_active=True)
    ts.active = True
    ts.target = f.today()
    db.commit()
    _q, _s = qstate(db, question_factory, n.id, ever_wrong=True, mastered=True)
    f.plan(db)
    assert db.query(ReviewRound).count() == 0
    ts.data = {**ts.data, "tags": []}
    db.commit()
    result = f.plan(db)
    assert db.query(ReviewRound).count() == 0 and any(
        "题库不足" in x for x in result["plan_notes"]
    )


def test_type_split_slices_only_count_once(db, question_factory, monkeypatch):
    n, ts = topic(db, ever_active=True)
    ts.active = True
    ts.target = f.today()
    db.commit()
    f.save_preferences(db, {"daily_minutes": 10, "type_min_questions": 2})
    _q1, _s1 = qstate(db, question_factory, n.id, minutes=8)
    _q2, _s2 = qstate(db, question_factory, n.id, minutes=8)
    result = f.plan(db)
    assert result["minutes"] == 8
    r = db.query(ReviewRound).one()
    ev = db.scalars(
        select(LearningEvent)
        .where(LearningEvent.kind == "type")
        .order_by(LearningEvent.day)
    ).all()
    assert len(ev) == 2 and ev[1].status == "planned"
    for i in round_items(db, r):
        if i.event_id == ev[0].id:
            f.record_item(db, i.id, {"verdict": "correct"})
    f.finish_slice(db, ev[0].id)
    assert r.status == "open" and ts.data.get("correct_streak", 0) == 0
    monkeypatch.setattr(f, "today", lambda: "2026-10-06")
    f.sync(db)
    for i in round_items(db, r):
        if i.event_id == ev[1].id:
            f.record_item(db, i.id, {"verdict": "correct"})
    with pytest.raises(AppError):
        f.finish_slice(db, ev[1].id)
    f.finish_slice(db, ev[1].id, passed=True)
    assert (
        r.status == "completed"
        and ts.data["correct_streak"] == 1
        and ts.target == "2026-10-13"
    )


def test_priority_balance_splits_bands_and_never_exceeds_twenty_percent(
    db, question_factory
):
    for subject in ("化学", "数学", "物理", "生物"):
        for index in range(5):
            q, _s = qstate(db, question_factory, subject=subject, minutes=20)
            f.mark_error(db, q.id, f.today(), f"{subject}-{index}", target=f.today())
    db.commit()
    result = f.plan(db)
    assert result["minutes"] == 80 and result["minutes"] <= 90
    today_events = [
        e for e in result["events"] if e["kind"] == "error" and e["day"] == f.today()
    ]
    assert [e["subject"] for e in today_events] == ["数学"]
    ids = [r.id for r in db.query(ReviewRound)]
    f.plan(db)
    assert ids == [r.id for r in db.query(ReviewRound)]
    all_events = db.scalars(
        select(LearningEvent).where(LearningEvent.kind == "error")
    ).all()
    for day in {e.day for e in all_events}:
        assert sum(e.minutes for e in all_events if e.day == day) <= 90
    assert sum(len(round_items(db, r)) for r in db.query(ReviewRound)) == 5


def test_oversize_question_stays_pending_instead_of_disappearing(db, question_factory):
    q, _s = qstate(db, question_factory, minutes=100)
    o = f.mark_error(db, q.id, f.today(), "large", target=f.today())
    db.commit()
    result = f.plan(db)
    assert (
        db.query(ReviewRound).count() == 0
        and o.status == "pending"
        and result["pending_errors"] == 1
    )
    assert result["plan_notes"]


def test_pdf_freezes_answer_version_and_has_links_but_no_answers(
    db, question_factory, tmp_path
):
    q, s = qstate(db, question_factory, answer="保密答案123", answer_confirmed=True)
    r = f.make_round(db, "error", "数学", f.today(), f.today(), [s])
    db.commit()
    e = round_event(db, r)
    path = export_pdf(db, e.id)
    data = path.read_bytes()
    s.answer = "changed"
    db.commit()
    assert export_pdf(db, e.id).read_bytes() == data
    item = round_items(db, r)[0]
    assert (
        item.data["answer"] == "保密答案123" and item.version_id == q.current_version_id
    )
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "保密答案" not in text and "Solve" in text
    links = [
        a.get_object().get("/A", {}).get("/URI", "")
        for p in reader.pages
        for a in p.get("/Annots", [])
    ]
    assert any(q.id in x and q.current_version_id in x for x in links)


def test_return_image_does_not_create_question_and_missing_answer_forces_uncertain(
    client, db, question_factory, png_bytes, monkeypatch
):
    _q, s = qstate(db, question_factory)
    r = f.make_round(db, "error", "数学", f.today(), f.today(), [s])
    db.commit()
    e = round_event(db, r)
    uploaded = client.post(
        "/api/v1/assets",
        files={"file": ("answer.png", png_bytes, "image/png")},
        data={"purpose": "answer"},
    ).json()
    assert uploaded["question_id"] is None and db.query(Question).count() == 1

    async def fake_grade(db, items, aid):
        assert items[0]["answer"] == "" and not items[0]["answer_confirmed"]
        return ai.Grading(
            items=[ai.GradedAnswer(number=1, verdict="correct", student_answer="1")]
        )

    monkeypatch.setattr(ai, "grade", fake_grade)
    response = client.post(
        f"/api/v1/learning/events/{e.id}/return",
        json={"asset_id": uploaded["asset_id"]},
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["data"]["ai_draft"]["verdict"] == "uncertain"
    assert response.json()["items"][0]["status"] != "resolved"


def test_knowledge_tree_leaf_enforcement_and_english_records(
    client, db, question_factory
):
    parent = client.post(
        "/api/v1/learning/knowledge",
        json={"subject": "数学", "kind": "type", "name": "代数"},
    ).json()
    child = client.post(
        "/api/v1/learning/knowledge",
        json={
            "subject": "数学",
            "kind": "type",
            "name": "方程",
            "parent_id": parent["id"],
        },
    ).json()
    q, _s = qstate(db, question_factory)
    assert (
        client.patch(
            f"/api/v1/learning/questions/{q.id}", json={"topic_id": parent["id"]}
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/v1/learning/questions/{q.id}", json={"topic_id": child["id"]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/learning/knowledge",
            json={"subject": "英语", "kind": "record", "name": "作文素材"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/learning/knowledge",
            json={"subject": "英语", "kind": "type", "name": "阅读"},
        ).status_code
        == 400
    )


def test_settings_persist_without_returning_secret(client):
    response = client.patch(
        "/api/v1/learning/settings",
        json={
            "preferences": {"daily_minutes": 60, "priority_enabled": False},
            "ai": {"key": "private-test-key"},
        },
    )
    assert response.status_code == 200 and "private-test-key" not in response.text
    assert (
        client.get("/api/v1/learning/settings").json()["preferences"]["daily_minutes"]
        == 60
    )
    assert (
        client.patch(
            "/api/v1/learning/settings", json={"preferences": {"redo_days": 0}}
        ).status_code
        == 400
    )
