from __future__ import annotations

import math
from datetime import date
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.questions import service as question_service
from app.db.models import Asset, KnowledgeNode, Question, QuestionVersion
from app.db.session import SessionLocal, get_db
from app.modules.learning import ai, imaging
from app.modules.learning import service as flow
from app.modules.learning.models import (
    LearningEvent,
    Occurrence,
    QuestionState,
    ReviewRound,
    RoundItem,
)
from app.modules.learning.pdf import export_pdf
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter(prefix="/learning")


def checked_day(value) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        flow.fail("日期格式不正确")


def node_view(db: Session, node: KnowledgeNode):
    ts = flow.topic_state(db, node.id) if node.kind == "type" else None
    return {
        "id": node.id,
        "name": node.name,
        "subject": node.subject,
        "kind": node.kind,
        "parent_id": node.parent_id,
        "summary": node.summary,
        "data": ts.data if ts else {},
        "cadence": ts.cadence if ts else None,
        "active": ts.active if ts else False,
        "target": ts.target if ts else None,
        "target_label": flow.label(ts.target) if ts and ts.target else None,
        "mastery": flow.topic_ratio(db, node.id) if ts else None,
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return flow.plan(db)


@router.post("/plan")
def plan(db: Session = Depends(get_db)):
    return flow.plan(db)


@router.get("/settings")
def settings(db: Session = Depends(get_db)):
    return {"preferences": flow.preferences(db), "ai": ai.public_configuration(db)}


@router.patch("/settings")
def update_settings(body: dict, db: Session = Depends(get_db)):
    if "preferences" in body:
        flow.save_preferences(db, body["preferences"])
    if "ai" in body:
        ai.save_configuration(db, body["ai"])
    return settings(db)


@router.get("/knowledge")
def knowledge(db: Session = Depends(get_db)):
    nodes = [
        node_view(db, n)
        for n in db.scalars(
            select(KnowledgeNode)
            .where(KnowledgeNode.status == "active")
            .order_by(KnowledgeNode.sort_order, KnowledgeNode.name)
        )
    ]
    db.commit()
    return {"items": nodes, "topic_tags": ["校外"]}


@router.post("/knowledge")
def create_node(body: dict, db: Session = Depends(get_db)):
    subject, kind, name = (
        str(body.get("subject", "")),
        str(body.get("kind", "")),
        str(body.get("name", "")).strip(),
    )
    if subject not in flow.ALL_SUBJECTS or not name or len(name) > 100:
        flow.fail("请填写有效学科及名称（最多100字）")
    if kind not in ("type", "knowledge", "record") or (
        kind == "type" and subject not in flow.SUBJECTS
    ):
        flow.fail("语文英语使用记录分类；题型检测仅适用于四科")
    stored_kind = "composition_category" if subject == "英语" else kind
    pid = body.get("parent_id") or None
    if pid:
        parent = db.get(KnowledgeNode, pid)
        if not parent or parent.subject != subject or parent.kind != stored_kind:
            flow.fail("父节点必须来自相同学科和分支")
        if kind == "type" and db.scalar(
            select(QuestionState).where(QuestionState.topic_id == pid)
        ):
            flow.fail("已有题目挂在这个叶子题型上，请先移走题目再增加子节点")
    if db.scalar(
        select(KnowledgeNode).where(
            KnowledgeNode.subject == subject,
            KnowledgeNode.kind == stored_kind,
            KnowledgeNode.parent_id == pid,
            KnowledgeNode.name == name,
            KnowledgeNode.status == "active",
        )
    ):
        flow.fail("这个分类下已经存在同名节点")
    node = KnowledgeNode(
        subject=subject,
        kind=stored_kind,
        name=name,
        parent_id=pid,
        summary=str(body.get("summary", "")),
    )
    db.add(node)
    db.flush()
    if kind == "type":
        flow.topic_state(db, node.id).data = {
            "tags": [],
            "method": "",
            "notes": "",
            "pain_points": "",
        }
    db.commit()
    return node_view(db, node)


@router.patch("/knowledge/{nid}")
def edit_node(nid: str, body: dict, db: Session = Depends(get_db)):
    node = db.get(KnowledgeNode, nid)
    if not node:
        flow.fail("知识节点不存在", status=404)
    if "name" in body:
        name = str(body["name"]).strip()
        if not name or len(name) > 100:
            flow.fail("名称不能为空或超过100字")
        duplicate = db.scalar(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == node.subject,
                KnowledgeNode.kind == node.kind,
                KnowledgeNode.parent_id == node.parent_id,
                KnowledgeNode.name == name,
                KnowledgeNode.id != node.id,
                KnowledgeNode.status == "active",
            )
        )
        if duplicate:
            flow.fail("已经有同名节点")
        node.name = name
    if "summary" in body:
        node.summary = str(body["summary"])
    if node.kind == "type":
        ts = flow.topic_state(db, nid)
        allowed = {
            k: body[k] for k in ("method", "notes", "pain_points", "tags") if k in body
        }
        if "tags" in allowed and (
            not isinstance(allowed["tags"], list)
            or any(not isinstance(t, str) for t in allowed["tags"])
        ):
            flow.fail("标签应为文本列表")
        ts.data = {**ts.data, **allowed}
    db.commit()
    flow.activate_topics(db, flow.today())
    db.commit()
    return node_view(db, node)


@router.post("/knowledge/{nid}/stop-decision")
def stop_decision(nid: str, body: dict, db: Session = Depends(get_db)):
    if not isinstance(body.get("stop"), bool):
        flow.fail("请明确确认是否停推")
    flow.confirm_stop(db, nid, body["stop"])
    return node_view(db, db.get(KnowledgeNode, nid))


@router.get("/questions")
def questions(
    subject: str = "",
    q: str = "",
    filter: str = "",
    topic_id: str = "",
    knowledge_id: str = "",
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    stmt = (
        select(Question)
        .where(Question.status != "deleted")
        .order_by(Question.created_at.desc())
    )
    if filter == "draft":
        stmt = stmt.where(Question.status == "draft")
    else:
        stmt = stmt.where(Question.status != "draft")
    if subject:
        stmt = stmt.where(Question.subject == subject)
    rows = [flow.question_view(db, row) for row in db.scalars(stmt)]
    if q:
        rows = [row for row in rows if q.lower() in json_text(row).lower()]
    if topic_id:
        ids = descendants(db, topic_id)
        rows = [row for row in rows if row["topic_id"] in ids]
    if knowledge_id:
        ids = descendants(db, knowledge_id)
        rows = [
            row
            for row in rows
            if ids.intersection(row["data"].get("knowledge_ids", []))
        ]
    if filter == "unmastered":
        rows = [row for row in rows if row["ever_wrong"] and not row["mastered"]]
    elif filter == "mastered":
        rows = [row for row in rows if row["ever_wrong"] and row["mastered"]]
    elif filter == "ordinary":
        rows = [row for row in rows if not row["ever_wrong"]]
    elif filter == "unassigned":
        rows = [row for row in rows if not row["topic_id"]]
    total = len(rows)
    db.commit()
    return {
        "items": rows[max(0, offset) : max(0, offset) + min(max(limit, 1), 500)],
        "total": total,
    }


def json_text(value):
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def descendants(db: Session, nid: str) -> set[str]:
    result, queue = {nid}, [nid]
    nodes = db.scalars(
        select(KnowledgeNode).where(KnowledgeNode.status == "active")
    ).all()
    while queue:
        parent = queue.pop()
        for node in nodes:
            if node.parent_id == parent and node.id not in result:
                result.add(node.id)
                queue.append(node.id)
    return result


@router.get("/questions/{qid}")
def question(qid: str, version: str = "", db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    result = flow.question_view(db, q)
    result["versions"] = [
        {"id": v.id, "number": v.version_number, "source": v.source} for v in q.versions
    ]
    if version:
        v = db.get(QuestionVersion, version)
        if not v or v.question_id != qid:
            flow.fail("原题版本不存在", status=404)
        result["content"] = flow.question_content(db, q, version)
        result["version_id"] = version
        result["historical"] = version != q.current_version_id
    result["occurrences"] = [
        {
            "id": o.id,
            "day": o.upload_date,
            "day_label": flow.label(o.upload_date),
            "target": flow.label(o.target),
            "status": o.status,
            "data": o.data,
        }
        for o in db.scalars(
            select(Occurrence)
            .where(Occurrence.question_id == qid)
            .order_by(Occurrence.upload_date)
        )
    ]
    db.commit()
    return result


async def recognize_background(qid: str):
    with SessionLocal() as db:
        q = flow.get_question(db, qid)
        s = flow.state_for(db, qid)
        s.data = {**s.data, "recognition": "running"}
        starting_version = q.current_version_id
        db.commit()
        try:
            output = await ai.recognize(
                db, q.source_asset_id, flow.question_content(db, q).get("stem", "")
            )
            db.refresh(q)
            db.refresh(s)
            if q.current_version_id != starting_version:
                s.data = {
                    **s.data,
                    "recognition": "review",
                    "recognition_draft": output.model_dump(),
                    "recognition_note": "识别期间题目已经修改，结果作为草稿保留，未覆盖你的内容",
                }
            else:
                question_service().update(db, q, {"content": output.model_dump()})
                processed = imaging.process_question(db, q.source_asset_id, output)
                s.data = {
                    **s.data,
                    **processed,
                    "recognition": "completed",
                    "recognition_note": "；".join(output.concerns + processed.get("image_processing_concerns", [])),
                    "suggested_type": output.suggested_type,
                    "suggested_knowledge": output.suggested_knowledge,
                }
            db.commit()
        except Exception as exc:  # noqa: BLE001 - Persist failure of a detached OCR job; never lose the archived source.
            db.rollback()
            s = flow.state_for(db, qid)
            s.data = {
                **s.data,
                "recognition": "failed",
                "recognition_note": str(exc)[:500],
            }
            db.commit()


@router.post("/intake")
def intake(body: dict, background: BackgroundTasks, db: Session = Depends(get_db)):
    day = checked_day(body.get("day", flow.today()))
    if body.get("is_error") and day > flow.today():
        flow.fail("错题日期不能在未来")
    subject = body.get("subject", "数学")
    if subject not in flow.ALL_SUBJECTS:
        flow.fail("请选择学科")
    qid = body.get("question_id")
    if qid:
        q = flow.get_question(db, qid)
    else:
        if not str(body.get("text", "")).strip():
            flow.fail("请上传图片或填写题目文字")
        q = Question(subject=subject, status="draft")
        db.add(q)
        db.commit()
    if db.get(QuestionState, q.id) and flow.state_for(db, q.id).data.get(
        "intake_complete"
    ):
        return question(q.id, db=db)
    q.status = "draft"
    question_service().update(
        db,
        q,
        {
            "subject": subject,
            "content": {
                "stem": str(body.get("text", "")),
                "options": [],
                "has_diagram": bool(body.get("has_diagram", False)),
            },
        },
    )
    s = flow.state_for(db, q.id)
    s.data = {
        **s.data,
        "intake_complete": True,
        "pending_error": bool(body.get("is_error")),
        "intake_day": day,
        "recognition": "queued"
        if q.source_asset_id
        and flow.preferences(db)["auto_recognize"]
        and ai.public_configuration(db)["configured"]
        else "manual",
        "recognition_note": (
            "原图已经归档；未配置AI或关闭自动识别时，请手动核对文字与图形"
            if q.source_asset_id
            else "文字稿已归档，可以继续校对、归类和确认标准答案"
        ),
    }
    flow.sync(db)
    db.commit()
    if s.data["recognition"] == "queued":
        background.add_task(recognize_background, q.id)
    return question(q.id, db=db)


@router.patch("/questions/{qid}")
def edit_question(qid: str, body: dict, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    s = flow.state_for(db, qid)
    if "answer_source" in body and body["answer_source"] not in ("manual", "bank", "ai"):
        flow.fail("答案来源无效")
    if "subject" in body and body["subject"] != q.subject:
        subject = body["subject"]
        if subject not in flow.ALL_SUBJECTS:
            flow.fail("请选择有效学科")
        if db.scalar(
            select(RoundItem)
            .join(ReviewRound)
            .where(RoundItem.question_id == qid, ReviewRound.status == "open")
        ):
            flow.fail("此题仍有待处理推送，请先处理完或放弃该轮，再更正学科")
        if s.ever_wrong and subject not in flow.SUBJECTS:
            flow.fail("已有四科错题记录不能直接改为语文英语，保留历史后可另建记录")
        q.subject = subject
        s.topic_id = None
        s.data = {**s.data, "knowledge_ids": []}
        for o in db.scalars(
            select(Occurrence).where(
                Occurrence.question_id == qid, Occurrence.status == "pending"
            )
        ):
            o.subject = subject
            flow.ensure_uploads(db, o.upload_date)
    if "minutes" in body:
        value = body["minutes"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not 0.5 <= value <= 600
        ):
            flow.fail("单题预计用时应在0.5至600分钟之间")
        s.minutes = value
    if "topic_id" in body:
        tid = body["topic_id"] or None
        node = db.get(KnowledgeNode, tid) if tid else None
        if tid and (
            not node
            or node.subject != q.subject
            or node.kind != "type"
            or node.status != "active"
        ):
            flow.fail("主题型必须来自当前学科的题型分支")
        if tid and db.scalar(
            select(KnowledgeNode).where(
                KnowledgeNode.parent_id == tid, KnowledgeNode.status == "active"
            )
        ):
            flow.fail("题目只能挂到叶子题型")
        s.topic_id = tid
        q.question_type = node.name if node else "待分类"
    if "knowledge_ids" in body:
        ids = body["knowledge_ids"]
        if not isinstance(ids, list):
            flow.fail("知识点应为列表")
        for kid in ids:
            n = db.get(KnowledgeNode, kid)
            if not n or n.kind != "knowledge" or n.subject != q.subject:
                flow.fail("关联知识点必须来自相同学科的知识点分支")
        s.data = {**s.data, "knowledge_ids": list(dict.fromkeys(ids))}
    if "answer" in body:
        s.answer = str(body["answer"]).strip()
        s.answer_confirmed = bool(s.answer) and body.get("answer_source", "manual") != "ai"
        s.data = {**s.data, "answer_source": body.get("answer_source", "manual"), "answer_asset_ids": []}
    if "answer_confirmed" in body:
        if body["answer_confirmed"] and not (s.answer or s.data.get("answer_asset_ids")):
            flow.fail("请先填写标准答案，再确认")
        s.answer_confirmed = bool(body["answer_confirmed"])
    if "answer_explanation" in body:
        s.data = {**s.data, "answer_explanation": str(body["answer_explanation"]).strip()}
        if s.data.get("answer_source") == "ai":
            s.answer_confirmed = bool(body.get("answer_confirmed", False))
    if "tags" in body:
        if not isinstance(body["tags"], list) or any(
            not isinstance(t, str) for t in body["tags"]
        ):
            flow.fail("题目标签应为文本列表")
        q.tags_json = list(dict.fromkeys(t.strip() for t in body["tags"] if t.strip()))
    if "content" in body:
        content = body["content"]
        if not isinstance(content, dict):
            flow.fail("题目内容应为对象")
        # Prevent a content edit from impersonating a confirmed grading answer.
        changes = {k: content[k] for k in ("stem", "options", "has_diagram") if k in content}
        previous = flow.question_content(db, q)
        if any(previous.get(k) != value for k, value in changes.items()):
            question_service().update(db, q, {"content": changes})
            if s.data.get("answer_source") == "ai":
                s.answer_confirmed = False
    flow.activate_topics(db, flow.today())
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/recognize")
def retry_recognize(
    qid: str, background: BackgroundTasks, db: Session = Depends(get_db)
):
    q = flow.get_question(db, qid)
    s = flow.state_for(db, qid)
    if not q.source_asset_id:
        flow.fail("这道题没有图片")
    if not ai.public_configuration(db)["configured"]:
        flow.fail("请先在设置中配置AI")
    if s.data.get("recognition") in ("running", "queued"):
        flow.fail("图片正在识别，请稍候")
    s.data = {**s.data, "recognition": "queued"}
    db.commit()
    background.add_task(recognize_background, qid)
    return {"queued": True}


@router.post("/questions/{qid}/analysis")
async def analyze_question(qid: str, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    starting_version = q.current_version_id
    output = await ai.analyze(db, flow.question_content(db, q), q.source_asset_id)
    db.refresh(q)
    if q.current_version_id != starting_version:
        flow.fail("解析期间题面已修改，请重新请求", "STALE_ANALYSIS", 409)
    s = flow.state_for(db, qid)
    s.data = {
        **s.data,
        "analysis": output.model_dump(),
        "analysis_version": q.current_version_id,
    }
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/crop")
def crop_question(qid: str, body: dict, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    source = db.get(Asset, q.source_asset_id)
    if not source:
        flow.fail("原图不存在")
    values = [body.get(k) for k in ("left", "top", "right", "bottom")]
    if any(
        isinstance(v, bool)
        or not isinstance(v, (float, int))
        or not math.isfinite(v)
        or not 0 <= v <= 1
        for v in values
    ):
        flow.fail("裁切坐标必须在原图范围内")
    left, top, right, bottom = values
    if right <= left or bottom <= top:
        flow.fail("请框选完整的题目或示意图")
    store = LocalFilesystemContentStore()
    with Image.open(BytesIO(store.read_bytes(source.storage_key))) as im:
        im = ImageOps.exif_transpose(im)
        width, height = im.size
        box = (
            int(left * width),
            int(top * height),
            int(right * width),
            int(bottom * height),
        )
        if box[2] - box[0] < 10 or box[3] - box[1] < 10:
            flow.fail("裁切区域过小")
        result = im.crop(box).convert("RGB")
        buf = BytesIO()
        result.save(buf, "PNG")
        key, digest = store.put_bytes("original-images", buf.getvalue(), ".png")
        asset = db.scalar(select(Asset).where(Asset.storage_key == key))
        if not asset:
            asset = Asset(
                kind="crop",
                storage_key=key,
                sha256=digest,
                mime_type="image/png",
                byte_size=len(buf.getvalue()),
                width=result.width,
                height=result.height,
            )
            db.add(asset)
            db.flush()
    s = flow.state_for(db, qid)
    s.data = {
        **s.data,
        "crop_asset_id": asset.id,
        "crop_history": [
            *s.data.get("crop_history", []),
            {
                "asset_id": asset.id,
                "source_asset_id": source.id,
                "box": values,
                "day": flow.today(),
            },
        ],
    }
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/error")
def manual_error(qid: str, body: dict, db: Session = Depends(get_db)):
    flow.sync(db)
    day = checked_day(body.get("day", flow.today()))
    if day > flow.today():
        flow.fail("错题日期不能在未来")
    flow.mark_error(db, qid, day, f"manual:{qid}:{day}")
    db.commit()
    return question(qid, db=db)


@router.post("/events")
def add_event(body: dict, db: Session = Depends(get_db)):
    flow.sync(db)
    title = str(body.get("title", "")).strip()
    if not title or len(title) > 200:
        flow.fail("事项名称不能为空或超过200字")
    day = checked_day(body.get("day", flow.today()))
    e = LearningEvent(
        key=f"manual:{uuid4()}",
        kind="general",
        title=title,
        subject=str(body.get("subject", "")),
        day=day,
        original_deadline=plus_week_end(day),
        week=flow.week(day),
        data={"notes": str(body.get("notes", ""))},
    )
    db.add(e)
    db.commit()
    return flow.event_view(e)


def plus_week_end(day):
    return flow.plus(flow.week(day), 6)


@router.post("/events/{eid}/action")
def event_action(eid: str, body: dict, db: Session = Depends(get_db)):
    flow.sync(db)
    action = body.get("action")
    if action == "no_errors" or action == "uploaded":
        return flow.finish_upload(db, eid, action == "no_errors")
    if action == "abandon":
        return flow.abandon_event(db, eid, str(body.get("reason", "")))
    e = flow.get_event(db, eid)
    if action == "complete" and e.kind == "general" and e.status == "open":
        e.status, e.completed_day = "completed", flow.today()
        db.commit()
        return flow.event_view(e)
    if action == "finish":
        return flow.finish_slice(db, eid, passed=body.get("passed"))
    flow.fail("该事项不能执行这个操作")


@router.get("/rounds/{rid}")
def round_detail(rid: str, db: Session = Depends(get_db)):
    flow.sync(db)
    return flow.round_view(db, rid)


@router.patch("/items/{iid}")
def grade_item(iid: str, body: dict, db: Session = Depends(get_db)):
    flow.sync(db)
    return flow.record_item(db, iid, body)


@router.get("/events/{eid}/pdf")
def pdf(eid: str, db: Session = Depends(get_db)):
    flow.sync(db)
    path = export_pdf(db, eid)
    return FileResponse(
        path, media_type="application/pdf", filename="learning-questions.pdf"
    )


@router.post("/items/{iid}/explanation")
async def wrong_explanation(iid: str, body: dict, db: Session = Depends(get_db)):
    flow.sync(db)
    item = db.get(RoundItem, iid)
    if not item:
        flow.fail("题目不存在", status=404)
    event = flow.get_event(db, item.event_id)
    if event.status != "open":
        flow.fail("事项已经结算，不能覆盖本轮记录")
    output = await ai.explain_wrong(
        db,
        item.data.get("content", {}),
        item.data.get("answer", "") if item.data.get("answer_confirmed") else "",
        str(body.get("student_answer", item.data.get("student_answer", ""))),
        item.data.get("crop_asset_id") or item.data.get("source_asset_id"),
    )
    db.refresh(item)
    db.refresh(event)
    if event.status != "open":
        flow.fail("处理期间事项已经结算，未覆盖历史记录")
    item.data = {
        **item.data,
        "explanation": output.explanation,
        "explanation_concerns": output.concerns,
    }
    db.commit()
    return flow.round_view(db, item.round_id)


@router.post("/events/{eid}/return")
async def return_answers(eid: str, body: dict, db: Session = Depends(get_db)):
    flow.sync(db)
    e = flow.get_event(db, eid)
    if e.kind not in ("type", "error") or e.status != "open":
        flow.fail("该推送无法继续回收")
    aid = body.get("asset_id")
    if not db.get(Asset, aid):
        flow.fail("请选择已上传的作答图片")
    e.data = {**e.data, "return_assets": [*e.data.get("return_assets", []), aid]}
    db.commit()
    items = db.scalars(
        select(RoundItem).where(RoundItem.event_id == eid).order_by(RoundItem.position)
    ).all()
    # AI outputs are drafts. User can correct them before making the independent mastery decision.
    if body.get("use_ai", True):
        data = [
            {
                "number": n,
                "question": i.data.get("content", {}),
                "answer": i.data.get("answer", "")
                if i.data.get("answer_confirmed")
                else "",
                "answer_confirmed": i.data.get("answer_confirmed", False),
                "answer_asset_ids": i.data.get("answer_asset_ids", []),
                "answer_explanation": i.data.get("answer_explanation", ""),
            }
            for n, i in enumerate(items, 1)
        ]
        output = await ai.grade(db, data, aid)
        db.expire_all()
        flow.sync(db)
        db.refresh(e)
        if e.status != "open":
            flow.fail("AI处理期间该事项已经结算；作答照片已保存，未覆盖历史判定")
        used = set()
        for draft in output.items:
            if 1 <= draft.number <= len(items) and draft.number not in used:
                used.add(draft.number)
                i = items[draft.number - 1]
                db.refresh(i)
                if i.status != "resolved":
                    verdict = (
                        draft.verdict
                        if draft.verdict in ("correct", "wrong", "uncertain")
                        else "uncertain"
                    )
                    if not i.data.get("answer_confirmed"):
                        verdict = "uncertain"
                    manual_values = (
                        {}
                        if i.data.get("audit")
                        else {
                            "student_answer": draft.student_answer,
                            "explanation": draft.explanation,
                        }
                    )
                    i.data = {
                        **i.data,
                        "ai_draft": {**draft.model_dump(), "verdict": verdict},
                        **manual_values,
                    }
        e.data = {**e.data, "grading_concerns": output.concerns}
        db.commit()
    return flow.round_view(db, e.data["round_id"])
