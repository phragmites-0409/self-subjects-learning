from __future__ import annotations

import json
import math
import random
import threading
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Asset, KnowledgeNode, Question, QuestionVersion, Setting
from app.documents.content import loads_compressed
from app.modules.learning.models import (
    LearningEvent,
    Occurrence,
    QuestionState,
    ReviewRound,
    RoundItem,
    TopicState,
    WeeklyReport,
)
from app.storage.local_store import LocalFilesystemContentStore

SUBJECTS = ["数学", "物理", "化学", "生物"]
ALL_SUBJECTS = SUBJECTS + ["语文", "英语"]
LOCK = threading.RLock()
DEFAULTS = {
    "redo_days": 7,
    "mastery_threshold": 80,
    "daily_minutes": 75,
    "priority_enabled": True,
    "priority_subjects": ["数学", "物理"],
    "correct_rounds": 2,
    "wrong_rounds": 2,
    "type_min_questions": 2,
    "default_question_minutes": 8,
    "auto_recognize": True,
    "type_review_enabled": False,
}


def today() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def plus(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def week(day: str) -> str:
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def label(day: str) -> str:
    d = date.fromisoformat(day[:10])
    return f"{d.month}月{d.day}日（星期{'一二三四五六日'[d.weekday()]}）"


def fail(message: str, code: str = "WORKFLOW_INVALID", status: int = 400):
    raise AppError(code, message, status)


def setting(db: Session, key: str, fallback=None):
    row = db.get(Setting, f"learning:{key}")
    return json.loads(row.value) if row else fallback


def set_setting(db: Session, key: str, value):
    row = db.get(Setting, f"learning:{key}")
    if not row:
        row = Setting(
            key=f"learning:{key}", value=json.dumps(value, ensure_ascii=False)
        )
        db.add(row)
    else:
        row.value = json.dumps(value, ensure_ascii=False)
    db.flush()


def preferences(db: Session) -> dict:
    return {**DEFAULTS, **setting(db, "preferences", {})}


def save_preferences(db: Session, changes: dict) -> dict:
    values = {**preferences(db), **{k: v for k, v in changes.items() if k in DEFAULTS}}
    ranges = {
        "redo_days": (1, 365),
        "mastery_threshold": (1, 100),
        "daily_minutes": (1, 600),
        "correct_rounds": (1, 20),
        "wrong_rounds": (1, 20),
        "type_min_questions": (1, 50),
        "default_question_minutes": (0.5, 120),
    }
    for key, (low, high) in ranges.items():
        value = values[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            fail(f"{key} 设置超出允许范围")
        if (
            key
            not in ("default_question_minutes", "daily_minutes", "mastery_threshold")
            and int(value) != value
        ):
            fail("天数、轮数和题数必须为整数")
    if not isinstance(values["priority_enabled"], bool) or not isinstance(
        values["auto_recognize"], bool
    ):
        fail("开关值必须是布尔值")
    if not isinstance(values["priority_subjects"], list) or any(
        s not in SUBJECTS for s in values["priority_subjects"]
    ):
        fail("优先学科必须来自数学、物理、化学、生物")
    if not isinstance(values["type_review_enabled"], bool):
        fail("题型重推开关必须为布尔值")
    set_setting(db, "preferences", values)
    reconcile_type_switches(db, today())
    activate_topics(db, today())
    db.commit()
    return values


def get_question(db: Session, qid: str) -> Question:
    q = db.get(Question, qid)
    if not q or q.status == "deleted":
        fail("题目不存在", "QUESTION_NOT_FOUND", 404)
    return q


def discard_draft(db: Session, qid: str) -> dict:
    """Delete an unfinished intake and its unshared source/derived photo files."""
    from app.modules.learning.draft_cleanup import finish_cleanup, prepare_cleanup

    with LOCK:
        q = db.get(Question, qid, populate_existing=True)
        if not q:
            fail("题目不存在", "QUESTION_NOT_FOUND", 404)
        state = db.get(QuestionState, qid)
        if q.status == "deleted" and (
            not state
            or state.data.get("draft_media_cleaned")
            or not state.data.get("draft_deleted_at")
        ):
            return {"id": qid, "deleted": True}
        if q.status not in ("draft", "deleted"):
            fail("此题已正式入库，不能作为草稿删除，请刷新列表", "DRAFT_ALREADY_ARCHIVED", 409)
        state = state_for(db, qid)
        if not state.data.get("draft_cleanup_pending"):
            prepare_cleanup(db, q, state)
        if not finish_cleanup(db, state):
            fail("草稿已移除，部分照片文件暂时无法删除，请重试；本地服务也会自动重试", "DRAFT_FILE_DELETE_FAILED", 503)
        return {"id": qid, "deleted": True}


def state_for(db: Session, qid: str) -> QuestionState:
    row = db.get(QuestionState, qid)
    if not row:
        row = QuestionState(
            question_id=qid,
            minutes=preferences(db)["default_question_minutes"],
            data={},
        )
        db.add(row)
        db.flush()
    return row


def question_content(db: Session, q: Question, version_id: str | None = None) -> dict:
    v = (
        db.get(QuestionVersion, version_id or q.current_version_id)
        if (version_id or q.current_version_id)
        else None
    )
    if not v:
        return {}
    try:
        payload = loads_compressed(
            LocalFilesystemContentStore().read_bytes(v.content_storage_key)
        )
    except (FileNotFoundError, ValueError):
        fail("题目版本文件缺失，不能用缺失内容生成推送", "CONTENT_MISSING", 500)
    return payload.get("content", payload)


def question_view(db: Session, q: Question) -> dict:
    s = state_for(db, q.id)
    topic = db.get(KnowledgeNode, s.topic_id) if s.topic_id else None
    asset = db.get(Asset, q.source_asset_id) if q.source_asset_id else None
    from app.modules.learning.knowledge import topic_issue
    return {
        "topic_issue": topic_issue(db, s.topic_id),
        "id": q.id,
        "subject": q.subject,
        "question_type": topic.name if topic else q.question_type,
        "status": q.status,
        "content": question_content(db, q),
        "tags": q.tags_json or [],
        "source_asset_id": q.source_asset_id,
        "source_sha256": asset.sha256 if asset else None,
        "version_id": q.current_version_id,
        "created_at": q.created_at,
        "topic_id": s.topic_id,
        "minutes": s.minutes,
        "answer": s.answer,
        "answer_confirmed": s.answer_confirmed,
        "ever_wrong": s.ever_wrong,
        "mastered": s.mastered,
        "latest_correct": s.latest_correct,
        "awaiting_correction": bool(db.scalar(select(Occurrence.id).where(Occurrence.question_id == q.id, Occurrence.status == "awaiting_correction").limit(1))),
        "data": s.data,
    }


def event_view(e: LearningEvent) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "title": e.title,
        "subject": e.subject,
        "day": e.day,
        "day_label": label(e.day),
        "original_deadline": e.original_deadline,
        "deadline_label": label(e.original_deadline),
        "week": e.week,
        "status": e.status,
        "minutes": e.minutes,
        "completed_day": e.completed_day,
        "data": e.data,
    }


def ensure_uploads(db: Session, day: str):
    for subject in SUBJECTS:
        key = f"upload:{day}:{subject}"
        if not db.scalar(select(LearningEvent).where(LearningEvent.key == key)):
            db.add(
                LearningEvent(
                    key=key,
                    kind="upload",
                    subject=subject,
                    title=f"{subject} · 当日错题上传",
                    day=day,
                    week=week(day),
                    original_deadline=day,
                    data={},
                )
            )
    db.flush()


def seal_week(db: Session, start: str):
    if db.get(WeeklyReport, start):
        return
    rows = db.scalars(select(LearningEvent).where(LearningEvent.week == start)).all()
    snapshot = [event_view(e) for e in rows]
    db.add(
        WeeklyReport(
            week=start,
            data={
                "week": start,
                "end": plus(start, 6),
                "label": f"{label(start)} - {label(plus(start, 6))}",
                "events": snapshot,
                "completed": [e for e in snapshot if e["status"] == "completed"],
                "unfinished": [e for e in snapshot if e["status"] == "open"],
                "paused": [e for e in snapshot if e["status"] == "paused"],
                "abandoned": [e for e in snapshot if e["status"] == "abandoned"],
                "carried": [e["id"] for e in snapshot if e["status"] == "open"],
            },
        )
    )
    for e in rows:
        if e.status == "open":
            e.data = {
                **e.data,
                "carry_history": [*e.data.get("carry_history", []), start],
            }
            e.week = plus(start, 7)
    db.flush()


def sync(db: Session, day: str | None = None):
    day = day or today()
    with LOCK:
        reconcile_type_switches(db, day)
        last = setting(db, "last_day")
        if not last:
            set_setting(db, "first_day", day)
            last = day
        while last < day:
            ensure_uploads(db, last)
            for e in db.scalars(
                select(LearningEvent).where(
                    LearningEvent.status == "planned", LearningEvent.day <= last
                )
            ):
                e.status = "open"
            db.flush()
            following = plus(last, 1)
            if week(last) != week(following):
                seal_week(db, week(last))
            last = following
        ensure_uploads(db, day)
        for e in db.scalars(
            select(LearningEvent).where(
                LearningEvent.status == "planned", LearningEvent.day <= day
            )
        ):
            e.status = "open"
        set_setting(db, "last_day", max(last, day))
        activate_topics(db, day)
        db.commit()


def finish_upload(db: Session, eid: str, no_errors: bool, day: str | None = None):
    e = get_event(db, eid)
    if e.kind != "upload" or e.status == "abandoned":
        fail("该事项不能按日清销账")
    count = len(
        db.scalars(
            select(Occurrence).where(
                Occurrence.upload_date == e.day,
                Occurrence.subject == e.subject,
                Occurrence.source_key.not_like("retry:%"),
            )
        ).all()
    )
    if no_errors and count:
        fail("当天已经记录错题，请选择上传完成")
    if not no_errors and not count:
        fail("当天还没有记录错题；无错题时请选择当日没有错题")
    e.status = "completed"
    e.completed_day = day or today()
    e.data = {
        **e.data,
        "outcome": "no_errors" if no_errors else "uploaded",
        "error_count": count,
    }
    db.commit()
    return event_view(e)


def get_event(db: Session, eid: str) -> LearningEvent:
    e = db.get(LearningEvent, eid)
    if not e:
        fail("事项不存在", "EVENT_NOT_FOUND", 404)
    return e


def get_round(db: Session, rid: str) -> ReviewRound:
    r = db.get(ReviewRound, rid)
    if not r:
        fail("推送轮次不存在", "ROUND_NOT_FOUND", 404)
    return r


def topic_state(db: Session, tid: str) -> TopicState:
    row = db.get(TopicState, tid)
    if not row:
        row = TopicState(topic_id=tid, data={})
        db.add(row)
        db.flush()
    return row


def topic_ratio(db: Session, tid: str) -> dict:
    rows = db.scalars(
        select(QuestionState)
        .join(Question)
        .where(
            QuestionState.topic_id == tid,
            QuestionState.ever_wrong == True,
            Question.status.notin_(["deleted", "draft"]),
        )
    ).all()
    rows = [s for s in rows if not s.data.get("correction_only")]
    mastered = sum(s.mastered for s in rows)
    return {
        "total": len(rows),
        "mastered": mastered,
        "ratio": round(mastered * 100 / len(rows), 2) if rows else None,
    }


def type_enabled(db: Session, tid: str) -> bool:
    return bool(preferences(db)["type_review_enabled"] and topic_state(db, tid).data.get("review_enabled", False))


def reconcile_type_switches(db: Session, day: str):
    for event in db.scalars(select(LearningEvent).where(LearningEvent.kind == "type", LearningEvent.status.in_(["open", "planned", "paused"]))):
        review = db.get(ReviewRound, event.data.get("round_id"))
        enabled = review and review.topic_id and type_enabled(db, review.topic_id)
        if not enabled and event.status != "paused" and not event.data.get("started_day") and not event.data.get("pdf_key") and not event.data.get("return_assets"):
            # A partially graded historical round is already in progress.
            if not db.scalar(select(RoundItem.id).where(RoundItem.event_id == event.id, RoundItem.status != "pending")):
                event.data = {**event.data, "resume_status": event.status}
                event.status = "paused"
        elif enabled and event.status == "paused":
            event.status = "planned" if event.day > day else "open"
            event.week = week(max(day, event.day))
    db.flush()


def activate_topics(db: Session, day: str):
    if not preferences(db)["type_review_enabled"]:
        return
    for node in db.scalars(
        select(KnowledgeNode).where(
            KnowledgeNode.kind == "type", KnowledgeNode.status == "active"
        )
    ):
        if db.scalar(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == node.id, KnowledgeNode.status == "active")):
            continue
        s = topic_state(db, node.id)
        if not s.data.get("review_enabled", False):
            continue
        ratio = topic_ratio(db, node.id)
        if (
            not s.active
            and not s.data.get("ever_active")
            and "校外" not in s.data.get("tags", [])
            and ratio["total"]
            and ratio["mastered"] * 100
            >= preferences(db)["mastery_threshold"] * ratio["total"]
        ):
            s.active, s.cadence, s.target = True, 7, plus(day, 7)
            s.data = {
                **s.data,
                "ever_active": True,
                "correct_streak": 0,
                "wrong_streak": 0,
            }


def mark_error(
    db: Session,
    qid: str,
    day: str,
    source_key: str,
    retry: bool = False,
    target: str | None = None,
    awaiting_correction: bool = False,
) -> Occurrence:
    existing = db.scalar(select(Occurrence).where(Occurrence.source_key == source_key))
    if existing:
        if existing.status == "corrected":
            existing.status = "pending"
            s = state_for(db, qid)
            s.ever_wrong, s.mastered, s.latest_correct = True, False, False
        return existing
    q = get_question(db, qid)
    if q.status == "draft":
        fail("请完成答案及题型后正式入库，再记录错题", "INTAKE_INCOMPLETE", 409)
    if q.subject not in SUBJECTS:
        fail("错题重做仅适用于数理化生四科")
    s = state_for(db, qid)
    correction_only = awaiting_correction and (not s.ever_wrong or s.data.get("correction_only", False))
    s.ever_wrong, s.mastered, s.latest_correct = True, False, False
    s.data = {**s.data, "correction_only": bool(correction_only)}
    o = Occurrence(
        question_id=qid,
        subject=q.subject,
        upload_date=day,
        # An empty target means that no countdown exists yet. Existing SQLite
        # databases keep their non-null target column and need no schema rewrite.
        target="" if awaiting_correction else target or plus(day, int(preferences(db)["redo_days"])),
        status="awaiting_correction" if awaiting_correction else "pending",
        source_key=source_key,
        data={"retry": retry},
    )
    db.add(o)
    db.flush()
    if not retry:
        ensure_uploads(db, day)
        e = db.scalar(
            select(LearningEvent).where(
                LearningEvent.key == f"upload:{day}:{q.subject}"
            )
        )
        if e.status == "completed":
            e.data = {**e.data, "outcome": "uploaded", "automatic_addition": True}
        if not awaiting_correction:
            flag_corrected_topic(db, s, day)
    return o


def flag_corrected_topic(db: Session, s: QuestionState, day: str):
    if not s.topic_id:
        return
    ts = topic_state(db, s.topic_id)
    ts.data = {**ts.data, "suspect": True}
    if type_enabled(db, s.topic_id) and not ts.active and ts.data.get("ever_active") and not ts.data.get("stop_pending"):
        ts.active, ts.cadence, ts.target = True, 15, plus(day, 15)
        ts.data = {**ts.data, "special_recheck": True}


def confirm_correction(db: Session, qid: str):
    with LOCK:
        q = get_question(db, qid)
        if q.status == "draft":
            fail("请先完成题目入库，再确认改错", "INTAKE_INCOMPLETE", 409)
        rows = db.scalars(select(Occurrence).where(Occurrence.question_id == qid, Occurrence.status == "awaiting_correction")).all()
        if not rows:
            return  # Retrying the same confirmation must not restart the countdown.
        day = today()
        interval = int(preferences(db)["redo_days"])
        for o in rows:
            o.status, o.target = "pending", plus(day, interval)
            o.data = {**o.data, "correction_day": day, "redo_days": interval}
        s = state_for(db, qid)
        s.ever_wrong, s.mastered, s.latest_correct = True, False, False
        s.data = {**s.data, "correction_only": False, "last_correction_day": day}
        flag_corrected_topic(db, s, day)
        activate_topics(db, day)
        db.commit()


def sampling_weight(s: QuestionState, q: Question) -> float:
    # The two groups have comparable additive influence. Only correctness uses latest outcome.
    tags = set(q.tags_json or [])
    label_weight = 2 if tags & {"重点题", "难题"} else 0
    correctness_weight = (
        2
        if s.latest_correct is False
        else (-0.5 if s.latest_correct is True else (1 if s.ever_wrong else -0.5))
    )
    return max(0.5, 2 + label_weight + correctness_weight)


def printable(db: Session, s: QuestionState) -> bool:
    if s.data.get("image_review_required"):
        return False
    q = get_question(db, s.question_id)
    if q.status == "draft":
        return False
    c = question_content(db, q)
    images=s.data.get('inline_images') or c.get('inline_images',[])
    import re
    anchors=set(re.findall(r'\[\[图块:(\d+)\]\]',c.get('stem','')+'\n'+'\n'.join(c.get('options',[]))))
    if anchors-{item['key'] for item in images}:return False
    images=[item for item in images if item['key'] in anchors]
    if c.get("has_diagram") and not s.data.get("crop_asset_id") and not any(item['kind']=='diagram' for item in images):
        return False
    return bool(c.get("stem", "").strip() or s.data.get("crop_asset_id"))


def eligible(db: Session, tid: str) -> list[QuestionState]:
    # Row ordering has an explicit per-topic previous-round ID, independent of split dates.
    ts = topic_state(db, tid)
    previous = ts.data.get("previous_round")
    excluded = (
        set(
            db.scalars(
                select(RoundItem.question_id).where(RoundItem.round_id == previous)
            ).all()
        )
        if previous
        else set()
    )
    return [
        s
        for s in db.scalars(
            select(QuestionState)
            .join(Question)
            .where(QuestionState.topic_id == tid, Question.status.notin_(["deleted", "draft"]))
        ).all()
        if not (s.ever_wrong and not s.mastered) and s.question_id not in excluded
    ]


def make_round(
    db: Session,
    kind: str,
    subject: str,
    target: str,
    day: str,
    states: list[QuestionState],
    topic_id: str | None = None,
    occurrences: list[Occurrence] | None = None,
    special: bool = False,
) -> ReviewRound:
    r = ReviewRound(
        kind=kind,
        subject=subject,
        topic_id=topic_id,
        target=target,
        day=day,
        data={"special_recheck": special},
    )
    db.add(r)
    db.flush()
    # One round can have several daily PDFs/events; never mixes subjects or types.
    e = make_slice(db, r, day, 1)
    for i, s in enumerate(states, 1):
        q = get_question(db, s.question_id)
        content = question_content(db, q)
        occurrence_ids = [o.id for o in (occurrences or []) if o.question_id == q.id]
        db.add(
            RoundItem(
                round_id=r.id,
                event_id=e.id,
                question_id=q.id,
                version_id=q.current_version_id,
                position=i,
                data={
                    "stem": content.get("stem", ""),
                    "content": content,
                    "answer": s.answer,
                    "answer_confirmed": s.answer_confirmed,
                    "answer_asset_ids": s.data.get("answer_asset_ids", []),
                    "answer_explanation": s.data.get("answer_explanation", ""),
                    "source_asset_id": q.source_asset_id,
                    "crop_asset_id": s.data.get("crop_asset_id"),
                    "inline_images": s.data.get('inline_images') or content.get('inline_images',[]),
                    "print_options_embedded": s.data.get("print_options_embedded", False),
                    "version_id": q.current_version_id,
                    "minutes": s.minutes,
                    "initial_state": {
                        "ever_wrong": s.ever_wrong,
                        "mastered": s.mastered,
                    },
                    "occurrences": occurrence_ids,
                    "audit": [],
                },
            )
        )
    e.minutes = sum(s.minutes for s in states)
    for o in occurrences or []:
        o.status = "assigned"
        o.data = {**o.data, "round_id": r.id}
    if topic_id:
        ts = topic_state(db, topic_id)
        ts.data = {**ts.data, "current_round": r.id, "previous_round": r.id}
    db.flush()
    return r


def make_slice(db: Session, r: ReviewRound, day: str, number: int) -> LearningEvent:
    node = db.get(KnowledgeNode, r.topic_id) if r.topic_id else None
    name = node.name if node else label(r.target)
    e = LearningEvent(
        key=f"round:{r.id}:{number}",
        kind=r.kind,
        subject=r.subject,
        title=f"{r.subject} · {'错题重做' if r.kind == 'error' else '自由练习' if r.kind == 'paper' else '题型重推'} · {name} · 第{number}份",
        day=day,
        week=week(day),
        original_deadline=plus(week(day), 6),
        data={
            "round_id": r.id,
            "slice": number,
            "target": r.target,
            "target_label": label(r.target),
        },
    )
    if day > today():
        e.status = "planned"
    db.add(e)
    db.flush()
    return e


def split_round(db: Session, r: ReviewRound, cap: float, used: float, day: str):
    items = db.scalars(
        select(RoundItem).where(RoundItem.round_id == r.id).order_by(RoundItem.position)
    ).all()
    events = db.scalars(
        select(LearningEvent).where(LearningEvent.key.like(f"round:{r.id}:%"))
    ).all()
    e = events[0]
    e.minutes = 0
    budget = preferences(db)["daily_minutes"]
    for item in items:
        minutes = item.data["minutes"]
        if used >= budget or used + minutes > cap + 0.001:
            day = plus(day, 1)
            used = sum(
                x.minutes
                for x in db.scalars(
                    select(LearningEvent).where(
                        LearningEvent.day == day,
                        LearningEvent.kind.in_(["error", "type", "paper"]),
                        LearningEvent.status.notin_(["abandoned", "paused"]),
                    )
                )
                if x not in events
            )
            while used >= budget or used + minutes > cap + 0.001:
                day = plus(day, 1)
                used = sum(
                    x.minutes
                    for x in db.scalars(
                        select(LearningEvent).where(
                            LearningEvent.day == day,
                            LearningEvent.kind.in_(["error", "type", "paper"]),
                            LearningEvent.status.notin_(["abandoned", "paused"]),
                        )
                    )
                    if x not in events
                )
            e = make_slice(db, r, day, len(events) + 1)
            events.append(e)
        item.event_id = e.id
        e.minutes += minutes
        used += minutes
    # No empty PDF/event when today's remaining allocation cannot fit its first question.
    for e in events:
        if e.minutes == 0:
            db.delete(e)
    db.flush()


def plan(db: Session, day: str | None = None) -> dict:
    day = day or today()
    with LOCK:
        sync(db, day)
        p = preferences(db)
        cap = round(p["daily_minutes"] * 1.2, 2)
        used = sum(
            e.minutes
            for e in db.scalars(
                select(LearningEvent).where(
                    LearningEvent.day == day,
                    LearningEvent.kind.in_(["error", "type", "paper"]),
                    LearningEvent.status.notin_(["abandoned", "paused"]),
                )
            )
        )
        reasons = []
        candidates = []
        for e in db.scalars(
            select(LearningEvent).where(
                LearningEvent.status == "open",
                LearningEvent.kind.in_(["error", "type", "paper"]),
                LearningEvent.day < day,
            )
        ):
            candidates.append(
                {"kind": "overdue", "subject": e.subject, "target": e.day, "event": e}
            )
        pending = db.scalars(
            select(Occurrence)
            .where(Occurrence.status == "pending", Occurrence.target <= day)
            .order_by(Occurrence.target, Occurrence.id)
        ).all()
        grouped = {}
        active_error_ids = set(db.scalars(select(RoundItem.question_id).join(ReviewRound, ReviewRound.id == RoundItem.round_id).where(ReviewRound.kind == "error", ReviewRound.status == "open", RoundItem.status != "abandoned")))
        for o in pending:
            q = db.get(Question, o.question_id)
            if not q or q.status == "deleted":
                reasons.append("有已删除题目的待重做记录，需要恢复题目或放弃记录")
                continue
            if state_for(db, q.id).mastered:
                o.status = "mastered"
                continue
            if q.id in active_error_ids:
                reasons.append("部分错题已在未完成的重做卷中，保留记录，待该轮处理后继续安排")
                continue
            grouped.setdefault(
                (o.subject, o.upload_date, bool(o.data.get("retry"))), []
            ).append(o)
        for (subject, _, _), occurrences in grouped.items():
            candidates.append(
                {
                    "kind": "error",
                    "subject": subject,
                    "target": min(o.target for o in occurrences),
                    "occurrences": occurrences,
                }
            )
        for ts in db.scalars(
            select(TopicState).where(
                TopicState.active == True, TopicState.target <= day
            )
        ):
            node = db.get(KnowledgeNode, ts.topic_id)
            current = (
                db.get(ReviewRound, ts.data.get("current_round"))
                if ts.data.get("current_round")
                else None
            )
            if (
                type_enabled(db, ts.topic_id)
                and node
                and node.status == "active"
                and not db.scalar(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == node.id, KnowledgeNode.status == "active"))
                and "校外" not in ts.data.get("tags", [])
                and not (current and current.status == "open")
                and not ts.data.get("stop_pending")
            ):
                candidates.append(
                    {
                        "kind": "type",
                        "subject": node.subject,
                        "target": ts.target,
                        "topic_id": node.id,
                    }
                )
        priorities = p["priority_subjects"] if p["priority_enabled"] else []
        candidates.sort(
            key=lambda c: (
                priorities.index(c["subject"])
                if c["subject"] in priorities
                else len(priorities),
                c["target"],
                0 if c["kind"] == "error" else 1,
                c["subject"],
            )
        )
        for c in candidates:
            remain = cap - used
            if remain <= 0:
                reasons.append(
                    f"{c['subject']}有待推内容，今日已达到用时上限，保留待排"
                )
                continue
            if c["kind"] == "overdue":
                e = c["event"]
                if e.minutes > remain:
                    e.data = {**e.data, "waiting_for_capacity": day}
                    reasons.append(
                        f"{e.title}：积压执行卷超过今日剩余容量，保留原事项和PDF待排"
                    )
                    continue
                e.data = {
                    **e.data,
                    "schedule_history": [*e.data.get("schedule_history", []), e.day],
                    "waiting_for_capacity": None,
                }
                e.day = day
                used += e.minutes
                if used >= p["daily_minutes"]:
                    break
                continue
            if c["kind"] == "error":
                ids = list(dict.fromkeys(o.question_id for o in c["occurrences"] if o.status == "pending"))
                states = [state_for(db, qid) for qid in ids]
                # Entire upload-date band is reserved; slices may be spread across future days.
                fit = [s for s in states if s.minutes <= cap and printable(db, s)]
                if len(fit) != len(states):
                    reasons.append(
                        f"{c['subject']}有题目用时超过上限或含图题未选定打印裁图，保留待排"
                    )
                if not fit:
                    continue
                if fit[0].minutes > remain:
                    reasons.append(
                        f"{c['subject']}今日剩余时间不足以容纳一题，保留待排"
                    )
                    continue
                chosen_ids = {s.question_id for s in fit}
                # One redo handles all due occurrences of each selected original question.
                occ = [o for o in pending if o.status == "pending" and o.question_id in chosen_ids]
                r = make_round(
                    db, "error", c["subject"], c["target"], day, fit, occurrences=occ
                )
                split_round(db, r, cap, used, day)
                used = sum(
                    e.minutes
                    for e in db.scalars(
                        select(LearningEvent).where(
                            LearningEvent.day == day,
                            LearningEvent.kind.in_(["error", "type", "paper"]),
                            LearningEvent.status.notin_(["abandoned", "paused"]),
                        )
                    )
                )
            else:
                pool = [s for s in eligible(db, c["topic_id"]) if printable(db, s)]
                minimum = int(p["type_min_questions"])
                if len(pool) < minimum:
                    reasons.append(
                        f"{c['subject']} · {db.get(KnowledgeNode, c['topic_id']).name}：排除未过手及上一轮题目后题库不足，本轮不推"
                    )
                    continue
                # Select a weighted round sized by the soft time allocation; if necessary split its minimum round.
                selected, available = [], list(pool)
                allowance = max(0, p["daily_minutes"] - used)
                total = 0
                while available:
                    weights = [
                        sampling_weight(s, get_question(db, s.question_id))
                        for s in available
                    ]
                    s = random.choices(available, weights=weights, k=1)[0]
                    available.remove(s)
                    if s.minutes > cap:
                        continue
                    if len(selected) >= minimum and total + s.minutes > allowance:
                        break
                    selected.append(s)
                    total += s.minutes
                    if len(selected) >= minimum and total >= allowance:
                        break
                if len(selected) < minimum:
                    reasons.append("题型的最小轮次无法安排，请修改单题用时或每日预算")
                    continue
                if selected[0].minutes > remain:
                    reasons.append("今日剩余时间不足以启动该题型，保留待排")
                    continue
                ts = topic_state(db, c["topic_id"])
                r = make_round(
                    db,
                    "type",
                    c["subject"],
                    c["target"],
                    day,
                    selected,
                    c["topic_id"],
                    special=bool(ts.data.get("special_recheck")),
                )
                split_round(db, r, cap, used, day)
                used = sum(
                    e.minutes
                    for e in db.scalars(
                        select(LearningEvent).where(
                            LearningEvent.day == day,
                            LearningEvent.kind.in_(["error", "type", "paper"]),
                            LearningEvent.status.notin_(["abandoned", "paused"]),
                        )
                    )
                )
            if used >= p["daily_minutes"]:
                break
        set_setting(
            db, "plan_notes", {"day": day, "reasons": list(dict.fromkeys(reasons))}
        )
        db.commit()
        return dashboard(db, day)


def round_view(db: Session, rid: str) -> dict:
    r = get_round(db, rid)
    items = db.scalars(
        select(RoundItem).where(RoundItem.round_id == rid).order_by(RoundItem.position)
    ).all()
    return {
        "id": r.id,
        "kind": r.kind,
        "subject": r.subject,
        "topic_id": r.topic_id,
        "target": r.target,
        "target_label": label(r.target),
        "day": r.day,
        "status": r.status,
        "data": r.data,
        "events": [
            event_view(e)
            for e in db.scalars(
                select(LearningEvent)
                .where(LearningEvent.key.like(f"round:{rid}:%"))
                .order_by(LearningEvent.day)
            )
        ],
        "items": [
            {
                "id": i.id,
                "event_id": i.event_id,
                "question_id": i.question_id,
                "position": i.position,
                "verdict": i.verdict,
                "status": i.status,
                "data": i.data,
            }
            for i in items
        ],
    }


def record_item(db: Session, iid: str, changes: dict, day: str | None = None) -> dict:
    day = day or today()
    with LOCK:
        i = db.get(RoundItem, iid)
        if not i:
            fail("作答题目不存在", "ITEM_NOT_FOUND", 404)
        r = get_round(db, i.round_id)
        if r.status != "open" or get_event(db, i.event_id).status != "open":
            fail("本轮或这份试卷已结算，不能覆盖历史结果")
        verdict = changes.get("verdict", i.verdict)
        if verdict not in ("correct", "wrong", "uncertain"):
            fail("请确认正确、错误或待人工改判")
        if "mastered" in changes and not isinstance(changes["mastered"], bool):
            fail("过手判断必须明确为是或否")
        if "learned" in changes and changes["learned"] is not True:
            fail("点击已学习时必须明确确认")
        before = {
            "verdict": i.verdict,
            "status": i.status,
            "student_answer": i.data.get("student_answer", ""),
        }
        if i.status == "resolved":
            # An open event remains reviewable. Retraction cannot affect an already-issued follow-up.
            retry = db.scalar(
                select(Occurrence).where(Occurrence.source_key == f"retry:{iid}")
            )
            created_error = db.scalar(
                select(Occurrence).where(Occurrence.source_key == f"{'paper' if r.kind == 'paper' else 'type'}:{iid}")
            )
            for o in (retry, created_error):
                if o and o.status == "assigned":
                    fail("后续试卷已经生成，不能覆盖其来源；请在后续轮次记录新判断")
            if retry:
                db.delete(retry)
            if created_error:
                created_error.status = "corrected"
                s = state_for(db, i.question_id)
                others = db.scalars(
                    select(Occurrence).where(
                        Occurrence.question_id == i.question_id,
                        Occurrence.id != created_error.id,
                        Occurrence.status != "corrected",
                    )
                ).all()
                s.ever_wrong = bool(others) or i.data.get("initial_state", {}).get(
                    "ever_wrong", False
                )
                s.mastered = i.data.get("initial_state", {}).get(
                    "mastered", False
                ) and not any(o.status in ("pending", "assigned") for o in others)
            for oid in i.data.get("occurrences", []):
                original = db.get(Occurrence, oid)
                if original:
                    original.status = "assigned"
            i.status = "pending"
            db.flush()
        event = get_event(db, i.event_id)
        event.data = {**event.data, "started_day": event.data.get("started_day", day)}
        i.verdict = verdict
        i.data = {
            **i.data,
            "student_answer": str(
                changes.get("student_answer", i.data.get("student_answer", ""))
            ),
            "explanation": str(
                changes.get("explanation", i.data.get("explanation", ""))
            ),
            "audit": [
                *i.data.get("audit", []),
                {
                    "day": day,
                    "day_label": label(day),
                    "before": before,
                    "verdict": verdict,
                    "source": "manual",
                },
            ],
        }
        if verdict == "uncertain":
            i.status = "pending"
        else:
            s = state_for(db, i.question_id)
            s.latest_correct = verdict == "correct"
            if r.kind == "error":
                s.mastered = False
            if r.kind == "error":
                if verdict == "correct" and "mastered" in changes:
                    s.mastered = changes["mastered"]
                    i.data = {**i.data, "mastered": s.mastered}
                    i.status = "resolved"
                    for oid in i.data.get("occurrences", []):
                        o = db.get(Occurrence, oid)
                        if o:
                            o.status = "mastered" if s.mastered else "processed"
                    if s.mastered:
                        for o in db.scalars(
                            select(Occurrence).where(
                                Occurrence.question_id == i.question_id,
                                Occurrence.status == "pending",
                            )
                        ):
                            o.status = "mastered"
                    else:
                        mark_error(
                            db, i.question_id, day, f"retry:{iid}", True, plus(day, 1)
                        )
                elif verdict == "wrong" and changes.get("learned"):
                    if not i.data.get("explanation", "").strip():
                        fail("请先记录解析或差异说明，再确认已学习")
                    i.data = {**i.data, "learned_day": day}
                    i.status = "resolved"
                    for oid in i.data.get("occurrences", []):
                        o = db.get(Occurrence, oid)
                        if o:
                            o.status = "processed"
                    mark_error(
                        db, i.question_id, day, f"retry:{iid}", True, plus(day, 1)
                    )
                else:
                    i.status = "judged"
            else:
                i.status = "resolved"
                if verdict == "wrong" and get_question(db, i.question_id).subject in SUBJECTS:
                    o = mark_error(db, i.question_id, day, f"{'paper' if r.kind == 'paper' else 'type'}:{iid}")
                    if o.status == "corrected":
                        o.status = "pending"
                        s.ever_wrong, s.mastered = True, False
        activate_topics(db, day)
        db.commit()
        return round_view(db, r.id)


def finish_slice(
    db: Session, eid: str, day: str | None = None, passed: bool | None = None
) -> dict:
    day = day or today()
    if passed is not None and not isinstance(passed, bool):
        fail("通过判断必须明确为是或否")
    with LOCK:
        e = get_event(db, eid)
        if e.status != "open" or e.kind not in ("error", "type", "paper"):
            fail("这份推送已经结算或不是推送事项")
        items = db.scalars(select(RoundItem).where(RoundItem.event_id == eid)).all()
        if not items or any(i.status != "resolved" for i in items):
            fail("先完成每道题的改判、过手判断或已学习确认")
        r = get_round(db, e.data["round_id"])
        all_items = db.scalars(
            select(RoundItem).where(RoundItem.round_id == r.id)
        ).all()
        events = db.scalars(
            select(LearningEvent).where(LearningEvent.key.like(f"round:{r.id}:%"))
        ).all()
        final_slice = all(
            x.id == eid or x.status not in ("open", "planned", "paused") for x in events
        )
        has_wrong = any(i.verdict == "wrong" for i in all_items)
        if (
            final_slice
            and r.kind == "type"
            and not has_wrong
            and not r.data.get("special_recheck")
            and passed is None
        ):
            fail("这轮题型全部正确，请人工确认通过或未通过")
        e.status, e.completed_day = "completed", day
        e.data = {
            **e.data,
            "result": "wrong"
            if any(i.verdict == "wrong" for i in items)
            else "correct",
        }
        if final_slice:
            if any(x.status == "abandoned" for x in events):
                r.status = "abandoned"
            else:
                r.status = "completed"
            r.data = {
                **r.data,
                "completed_day": day,
                "passed": False if has_wrong else bool(passed),
                "has_wrong": has_wrong,
            }
            if r.kind == "type":
                update_frequency(db, r, day, has_wrong, bool(passed))
        db.commit()
        return round_view(db, r.id)


def update_frequency(
    db: Session, r: ReviewRound, day: str, has_wrong: bool, passed: bool
):
    ts = topic_state(db, r.topic_id)
    data = {**ts.data, "current_round": None, "last_handled": day}
    if r.status == "abandoned":
        ts.target = plus(day, ts.cadence)
        ts.data = data
        return
    if r.data.get("special_recheck") and not has_wrong:
        ts.active, ts.target = False, None
        ts.data = {
            **data,
            "special_recheck": False,
            "correct_streak": 0,
            "wrong_streak": 0,
            "suspect": False,
        }
        r.data = {**r.data, "automatic_stop": True, "passed": True}
        return
    p = preferences(db)
    if has_wrong:
        data.update(
            suspect=True,
            correct_streak=0,
            wrong_streak=data.get("wrong_streak", 0) + 1,
            special_recheck=False,
        )
        if data["wrong_streak"] >= p["wrong_rounds"]:
            ts.cadence = {15: 7, 7: 3, 3: 3}[ts.cadence]
            data.update(correct_streak=0, wrong_streak=0)
    else:
        data.update(
            correct_streak=data.get("correct_streak", 0) + 1,
            wrong_streak=0,
            special_recheck=False,
        )
        if passed:
            data["suspect"] = False
            if data["correct_streak"] >= p["correct_rounds"]:
                if ts.cadence == 15:
                    data["stop_pending"] = True
                else:
                    ts.cadence = {3: 7, 7: 15}[ts.cadence]
                data.update(correct_streak=0, wrong_streak=0)
        # All correct but manual fail: preserve streak, never lower frequency this round.
    ts.target = plus(day, ts.cadence)
    ts.data = data


def confirm_stop(db: Session, tid: str, stop: bool):
    ts = topic_state(db, tid)
    if not ts.data.get("stop_pending"):
        fail("这个题型当前没有等待停推确认")
    ts.data = {**ts.data, "stop_pending": False, "correct_streak": 0, "wrong_streak": 0}
    if stop:
        ts.active, ts.target = False, None
    db.commit()


def abandon_event(db: Session, eid: str, reason: str = "", day: str | None = None):
    day = day or today()
    e = get_event(db, eid)
    if e.status not in ("open", "planned", "paused"):
        fail("只能放弃未完成事项")
    e.status, e.completed_day = "abandoned", day
    e.data = {**e.data, "abandon_reason": reason, "abandoned_day": day}
    if e.kind in ("error", "type", "paper"):
        r = get_round(db, e.data["round_id"])
        for i in db.scalars(select(RoundItem).where(RoundItem.event_id == eid)):
            if i.status != "resolved":
                i.status = "abandoned"
                for oid in i.data.get("occurrences", []):
                    o = db.get(Occurrence, oid)
                    if o:
                        o.status = "abandoned"
        other = db.scalars(
            select(LearningEvent).where(
                LearningEvent.key.like(f"round:{r.id}:%"), LearningEvent.id != eid
            )
        ).all()
        if all(x.status not in ("open", "planned", "paused") for x in other):
            r.status = "abandoned"
            r.data = {**r.data, "completed_day": day}
            if r.topic_id:
                update_frequency(db, r, day, False, False)
    if e.kind == "vocabulary":
        from app.modules.vocabulary.models import VocabularySession, SessionWord
        session = db.get(VocabularySession, e.data.get("session_id"))
        if session:
            session.status = "abandoned"
            for item in db.scalars(select(SessionWord).where(SessionWord.session_id == session.id, SessionWord.status.in_(["pending", "review", "retry"]))):
                item.status = "abandoned"
    db.commit()
    return event_view(e)


def dashboard(db: Session, day: str | None = None) -> dict:
    day = day or today()
    sync(db, day)
    from app.modules.vocabulary.service import ensure_session
    ensure_session(db, day)
    p = preferences(db)
    events = db.scalars(
        select(LearningEvent)
        .where(LearningEvent.week == week(day))
        .order_by(LearningEvent.day, LearningEvent.kind)
    ).all()
    # Future slices are visible, but are not included in this week's settlement until that week.
    upcoming = db.scalars(
        select(LearningEvent)
        .where(LearningEvent.day > plus(week(day), 6), LearningEvent.status == "open")
        .order_by(LearningEvent.day)
    ).all()
    today_events = [e for e in events if e.day == day]
    minutes = round(
        sum(
            e.minutes
            for e in today_events
            if e.kind in ("type", "error", "paper") and e.status not in ("abandoned", "paused")
        ),
        2,
    )
    pending = db.scalars(select(Occurrence).where(Occurrence.status == "pending")).all()
    notes = setting(db, "plan_notes", {})
    return {
        "day": day,
        "day_label": label(day),
        "week": week(day),
        "week_end_label": label(plus(week(day), 6)),
        "preferences": p,
        "minutes": minutes,
        "maximum": round(p["daily_minutes"] * 1.2, 2),
        "events": [event_view(e) for e in events],
        "upcoming": [event_view(e) for e in upcoming],
        "uploads": [event_view(e) for e in today_events if e.kind == "upload"],
        "pending_errors": len(pending),
        "pending_minutes": round(
            sum(state_for(db, o.question_id).minutes for o in pending), 2
        ),
        "reports": [
            r.data
            for r in db.scalars(select(WeeklyReport).order_by(WeeklyReport.week.desc()))
        ],
        "plan_notes": notes.get("reasons", []) if notes.get("day") == day else [],
        "waiting_topics": [
            {
                "id": s.topic_id,
                "name": db.get(KnowledgeNode, s.topic_id).name,
                "data": s.data,
            }
            for s in db.scalars(select(TopicState))
            if s.data.get("stop_pending") and type_enabled(db, s.topic_id)
        ],
    }
