from __future__ import annotations

import math
import json
from datetime import date
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, Query
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.questions import service as question_service
from app.core.account_scope import schedule
from app.db.models import Asset, KnowledgeNode, Question, QuestionVersion
from app.db.session import SessionLocal, get_db
from app.modules.learning import ai, imaging
from app.modules.learning import knowledge as kb
from app.modules.learning.subject_detection import detect_subject
from app.modules.learning.intake_context import apply_category, normalize_context
from app.modules.learning.note_filter import boxes_for
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
        "data": {**(ts.data if ts else {}), **kb.content_for(db, node).data},
        "child_count": len(kb.active_children(db, node.id)),
        "issue_count": len(kb.issue_questions(db, node)),
        "cadence": ts.cadence if ts else None,
        "active": ts.active if ts else False,
        "target": ts.target if ts else None,
        "target_label": flow.label(ts.target) if ts and ts.target else None,
        "mastery": kb.aggregate_mastery(db, node) if ts else None,
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return flow.plan(db)


@router.post("/plan")
def plan(db: Session = Depends(get_db)):
    return flow.plan(db)


@router.post("/knowledge/{tid}/review-switch")
def review_switch(tid: str, body: dict, db: Session = Depends(get_db)):
    node = db.get(KnowledgeNode, tid)
    if not node or node.kind != "type" or node.status != "active" or kb.active_children(db, tid):
        flow.fail("请选择有效的叶子题型")
    if type(body.get("enabled")) is not bool:
        flow.fail("请明确是否启用")
    with flow.LOCK:
        state = flow.topic_state(db, tid)
        state.data = {**state.data, "review_enabled": body["enabled"]}
        flow.reconcile_type_switches(db, flow.today())
        flow.activate_topics(db, flow.today())
        db.commit()
    return node_view(db, node)


@router.get("/settings")
def settings(db: Session = Depends(get_db)):
    return {
        "preferences": flow.preferences(db),
        "ai": ai.public_configuration(db),
        "recognition": ai.public_recognition_configuration(db),
    }


@router.get("/notifications")
def notification_status(db: Session = Depends(get_db)):
    from app.modules.notifications import status
    return status(db)


@router.patch("/notifications")
def notification_settings(body: dict, db: Session = Depends(get_db)):
    from app.modules.notifications import save_preferences
    return save_preferences(db, body)


@router.post("/notifications/test")
def notification_test(db: Session = Depends(get_db)):
    from app.modules.notifications import send_test
    try:
        return send_test(db)
    except Exception as exc:
        flow.fail(f"桌面通知未发送：{exc}")


@router.patch("/settings")
def update_settings(body: dict, db: Session = Depends(get_db)):
    if "preferences" in body:
        flow.save_preferences(db, body["preferences"])
    if "ai" in body:
        ai.save_configuration(db, body["ai"])
    if "recognition" in body:
        ai.save_recognition_configuration(db, body["recognition"])
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
    return {"items": nodes, "topic_tags": kb.tag_catalog(db)["node"], "tag_catalog": kb.tag_catalog(db)}


@router.post("/knowledge")
def create_node(body: dict, db: Session = Depends(get_db)):
    subject, kind, name = (
        str(body.get("subject", "")),
        str(body.get("kind", "")),
        str(body.get("name", "")).strip(),
    )
    if subject not in flow.ALL_SUBJECTS or not name or len(name) > 100:
        flow.fail("请填写有效学科及名称（最多100字）")
    if kind not in (("type", "knowledge") if subject in flow.SUBJECTS else ("record",)):
        flow.fail("语文英语使用记录分类；题型检测仅适用于四科")
    stored_kind = "composition_category" if subject == "英语" else kind
    pid = body.get("parent_id") or None
    if pid:
        parent = db.get(KnowledgeNode, pid)
        if not parent or parent.subject != subject or (parent.kind != stored_kind if subject != "英语" else parent.kind not in ("composition_category", "phrase", "sentence_pattern", "viewpoint", "material", "sample_excerpt")) or parent.status != "active":
            flow.fail("父节点必须来自相同学科和分支")
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
    kb.content_for(db, node)
    db.commit()
    return node_view(db, node)


@router.patch("/knowledge/{nid}")
def edit_node(nid: str, body: dict, db: Session = Depends(get_db)):
    node = db.get(KnowledgeNode, nid)
    if not node:
        flow.fail("知识节点不存在", status=404)
    content = kb.content_for(db, node)
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
    from copy import deepcopy
    data = deepcopy(content.data)
    if "material_type" in body:
        if node.subject != "英语" or body["material_type"] not in kb.MATERIALS:
            flow.fail("请选择有效的作文素材类型")
        data["material_type"] = body["material_type"]
    if "tags" in body:
        data["tags"] = kb.tags(body["tags"])
        kb.remember_tags(db, "node", kb.tags(body.get("tag_options", [])) + data["tags"])
        if node.kind == "type":
            ts.data = {**ts.data, "tags": data["tags"]}
    # Compatibility callers update their own migrated entry, never all entries.
    for key, collection, title in [("summary", "note_entries", "原有正文"), ("method", "note_entries", "解题思路"), ("notes", "note_entries", "学习笔记"), ("pain_points", "pain_entries", "待改进问题")]:
        if key not in body:
            continue
        value = str(body[key])
        old = next((e for e in data[collection] if e["id"] == "legacy-" + key), None)
        if value.strip():
            if old:
                old["body"], old["revision"] = value, old["revision"] + 1
            else:
                data[collection].append({"id": "legacy-"+key, "title": title, "body": value, "tags": [], "images": [], "source": "manual", "confirmed": True, "pinned": False, "revision": 1})
        elif old:
            data[collection].remove(old)
    content.data = data
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
    tag: str = "",
    untagged: bool = False,
    issues_only: bool = False,
    direct_topic: bool = False,
    topic_ids: list[str] = Query(default=[]),
    tags: list[str] = Query(default=[]),
    tag_mode: str = "all",
    date_from: str = "",
    date_to: str = "",
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    from app.modules.question_bank.service import list_questions
    with flow.LOCK:
        return list_questions(db, subject=subject, q=q, filter=filter, topic_id=topic_id,
            topic_ids=topic_ids, knowledge_id=knowledge_id, tag=tag, tags=tags,
            tag_mode=tag_mode, untagged=untagged, issues_only=issues_only,
            direct_topic=direct_topic, date_from=date_from, date_to=date_to,
            offset=offset, limit=limit)


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
            "target": flow.label(o.target) if o.target else None,
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


@router.delete("/questions/{qid}/draft")
def delete_draft(qid: str, db: Session = Depends(get_db)):
    return flow.discard_draft(db, qid)


async def recognize_background(qid: str, source_aid: str | None = None, review_only=False):
    with SessionLocal() as db:
        with flow.LOCK:
            q = db.get(Question, qid)
            if not q or q.status == "deleted":
                return
            s = flow.state_for(db, qid)
            s.data = {**s.data, "recognition": "running"}
            starting_version = q.current_version_id
            starting_notes = json.loads(json.dumps(s.data.get("note_filters",{})))
            db.commit()
        try:
            source_aid = source_aid or q.source_asset_id
            hint = flow.question_content(db, q).get("stem", "")
            pages = s.data.get("source_pages", [])
            exclusions=boxes_for(q,s)
            if len(pages) > 1:
                from app.modules.learning import question_pages
                known_regions = s.data.get("image_diagram_regions") if s.data.get("image_geometry_version_id") == starting_version else None
                output = await question_pages.recognize(db, source_aid, q.source_asset_id, pages, hint, flow.question_content(db, q), known_regions, exclusions)
            else:
                output = await ai.recognize(db, source_aid, hint, exclusions) if exclusions else await ai.recognize(db, source_aid, hint)
            with flow.LOCK:
                db.refresh(q)
                db.refresh(s)
                if q.status == "deleted":
                    return
                if review_only or q.current_version_id != starting_version or s.data.get("note_filters",{}) != starting_notes:
                    draft=output.model_dump()
                    draft['inline_images']=imaging.inline_assets(db,source_aid,output,ai.recognition_configuration(db)['ink'] if source_aid==q.source_asset_id else 'off',exclusions)
                    s.data = {
                        **s.data,
                        "recognition": "review",
                        "recognition_draft": draft,
                        "recognition_draft_version": starting_version,
                        "recognition_draft_source": source_aid,
                        "recognition_draft_note_filters": starting_notes,
                        "recognition_info": output._ocr_metadata,
                        "recognition_note": "重新提取的文字和裁图范围已作为草稿保留，请核对后采用；现有题目内容保留",
                    }
                else:
                    if q.status == "draft" and s.data.get("subject_source") in ("pending", "auto", "unknown"):
                        identified = output.subject if output.subject in flow.ALL_SUBJECTS else ""
                        if identified:
                            q.subject = identified
                            s.topic_id = None
                        s.data = {**s.data, "subject_source": "auto" if identified else "unknown",
                                  "recognized_subject": identified, "knowledge_ids": []}
                    apply_category(db, q, s)
                    processed = imaging.process_question(
                        db,
                        q.source_asset_id,
                        output,
                        output._ocr_metadata.get("ink", "off"),
                        ai.recognition_configuration(db).get("pencil", "balanced"),
                        exclusions,
                    )
                    question_service().update(db, q, {"content":{**output.model_dump(),'inline_images':processed.get('inline_images',[])}})
                    s.data = {
                        **s.data,
                        **processed,
                        "recognition": "completed",
                        "recognition_note": "；".join(
                            output.concerns + processed.get("image_processing_concerns", [])
                        ),
                        "suggested_type": output.suggested_type,
                        "suggested_knowledge": output.suggested_knowledge,
                        "recognition_info": output._ocr_metadata,
                        "image_diagram_regions": [r.model_dump() for r in output.diagram_regions],
                        "image_geometry_version_id": q.current_version_id,
                    }
                db.commit()
        except Exception as exc:  # noqa: BLE001 - Persist failure of a detached OCR job; never lose the archived source.
            db.rollback()
            with flow.LOCK:
                q = db.get(Question, qid, populate_existing=True)
                if not q or q.status == "deleted":
                    return
                s = flow.state_for(db, qid)
                s.data = {
                    **s.data,
                    "recognition": "failed",
                    "recognition_note": str(exc)[:500],
                }
                db.commit()


@router.post("/intake/photos")
async def upload_question_photos(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    from app.api.v1.assets import upload_asset
    from app.modules.learning.question_pages import MAX_PAGES, assemble
    if not 2 <= len(files) <= MAX_PAGES:
        flow.fail(f"同题多图请选择2至{MAX_PAGES}张照片", "INVALID_PAGE_COUNT", 422)
    sources = []
    for file in files:
        uploaded = await upload_asset(file, text="", purpose="question_page", db=db)
        sources.append({"asset_id": uploaded["asset_id"], "thumbnail_asset_id": uploaded["thumbnail_asset_id"], "filename": (file.filename or "照片")[:200],
                        "width": uploaded["width"], "height": uploaded["height"], "sha256": uploaded["sha256"]})
    asset, pages = assemble(db, sources)
    q = question_service().create_from_asset(db, asset)
    state = flow.state_for(db, q.id)
    state.data = {**state.data, "source_pages": pages}
    db.commit()
    return {"question_id": q.id, "source_pages": pages}


@router.post("/intake")
def intake(body: dict, background: BackgroundTasks, db: Session = Depends(get_db)):
    day = checked_day(body.get("day", flow.today()))
    if body.get("is_error") and day > flow.today():
        flow.fail("错题日期不能在未来")
    auto_subject = body.get("subject") in (None, "", "auto")
    detection = detect_subject(str(body.get("text", ""))) if auto_subject else {}
    subject = (detection.get("subject") or "数学") if auto_subject else body["subject"]
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
        "intake_context": normalize_context(body.get("context"), day),
        "subject_source": ("pending" if q.source_asset_id else "auto" if detection.get("subject") else "unknown") if auto_subject else "manual",
        "recognized_subject": detection.get("subject", ""),
        "pending_error": bool(body.get("is_error")),
        "intake_day": day,
        "recognition": "queued"
        if q.source_asset_id
        and flow.preferences(db)["auto_recognize"]
        and ai.recognition_available(db)
        else "manual",
        "recognition_note": (
            "原图已经归档；识别未准备好或关闭自动识别时，请手动核对文字与图形"
            if q.source_asset_id
            else "文字稿已归档，可以继续校对、归类和确认标准答案"
        ),
    }
    if s.data["recognition"] == "manual" and s.data["subject_source"] not in ("pending", "unknown"):
        apply_category(db, q, s)
    flow.sync(db)
    db.commit()
    if s.data["recognition"] == "queued":
        schedule(background, recognize_background, q.id)
    return question(q.id, db=db)


@router.patch("/questions/{qid}")
def edit_question(qid: str, body: dict, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    s = flow.state_for(db, qid)
    if 'version_id' in body and body['version_id']!=q.current_version_id:
        flow.fail('题目版本已变化，请刷新后重新校对，避免覆盖新内容','STALE_RECOGNITION',409)
    if "answer_source" in body and body["answer_source"] not in (
        "manual",
        "bank",
        "ai",
    ):
        flow.fail("答案来源无效")
    if "subject" in body and body["subject"] not in flow.ALL_SUBJECTS:
        flow.fail("请选择有效学科")
    if "subject" in body:
        s.data = {**s.data, "subject_source": "manual"}
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
                Occurrence.question_id == qid, Occurrence.status.in_(["pending", "awaiting_correction"])
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
        if tid and tid != s.topic_id and db.scalar(
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
        s.answer_confirmed = (
            bool(s.answer) and body.get("answer_source", "manual") != "ai"
        )
        s.data = {
            **s.data,
            "answer_source": body.get("answer_source", "manual"),
            "answer_asset_ids": [],
        }
    if "answer_confirmed" in body:
        if body["answer_confirmed"] and not (
            s.answer or s.data.get("answer_asset_ids")
        ):
            flow.fail("请先填写标准答案，再确认")
        s.answer_confirmed = bool(body["answer_confirmed"])
    if "answer_explanation" in body:
        s.data = {
            **s.data,
            "answer_explanation": str(body["answer_explanation"]).strip(),
        }
        if s.data.get("answer_source") == "ai":
            s.answer_confirmed = bool(body.get("answer_confirmed", False))
    if "tags" in body:
        if not isinstance(body["tags"], list) or any(
            not isinstance(t, str) for t in body["tags"]
        ):
            flow.fail("题目标签应为文本列表")
        q.tags_json = kb.tags(body["tags"])
        kb.remember_tags(db, "question", kb.tags(body.get("tag_options", [])) + q.tags_json)
    if "content" in body:
        content = body["content"]
        if not isinstance(content, dict):
            flow.fail("题目内容应为对象")
        # Prevent a content edit from impersonating a confirmed grading answer.
        changes = {
            k: content[k] for k in ("stem", "options", "has_diagram") if k in content
        }
        previous = flow.question_content(db, q)
        if 'stem' in changes or 'options' in changes:
            import re
            images=s.data.get('inline_images') or previous.get('inline_images',[])
            keys={item['key'] for item in images}
            text=changes.get('stem',previous.get('stem',''))+'\n'+'\n'.join(changes.get('options',previous.get('options',[])))
            if any(key not in keys for key in re.findall(r'\[\[图块:(\d+)\]\]',text)):
                flow.fail('题干引用了不存在的公式或题图编号，请核对占位符','INLINE_IMAGE_MISSING',422)
            if images:
                active=set(re.findall(r'\[\[图块:(\d+)\]\]',text))
                kept=[item for item in images if item['key'] in active]
                changes['inline_images']=kept
                changes['inline_regions']=[item for item in previous.get('inline_regions',[]) if item['key'] in active]
                if kept!=images:
                    from app.api.v1.image_edit import remember
                    remember(s)
                    s.data={**s.data,'inline_images':kept,'image_confirmed_inline_ids':None,'image_review_required':bool(kept) or bool(changes.get('has_diagram',previous.get('has_diagram')))}
        if any(previous.get(k) != value for k, value in changes.items()):
            question_service().update(db, q, {"content": changes})
            if s.data.get("answer_source") == "ai":
                s.answer_confirmed = False
    flow.activate_topics(db, flow.today())
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/notes/filter")
def filter_question_notes(qid: str, body: dict, background: BackgroundTasks, db: Session = Depends(get_db)):
    q=flow.get_question(db,qid);state=flow.state_for(db,qid)
    if state.data.get("recognition") in ("queued","running"):
        flow.fail("请等待当前识别完成", "IMAGE_BUSY", 409)
    if body.get("version_id") != q.current_version_id:
        flow.fail("题目版本已变化，请刷新后标记", "STALE_RECOGNITION", 409)
    pages=state.data.get("source_pages",[]) or [{"asset_id":q.source_asset_id,"box":[0,0,1,1]}]
    index=body.get("page_index",0);boxes=body.get("boxes",[])
    if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(pages) or not isinstance(boxes,list) or len(boxes)>16:
        flow.fail("请选择本题原图，每张最多16个排除框", "INVALID_NOTE_BOX", 422)
    page=pages[index];image=imaging.load_image(db,page["asset_id"])
    for box in boxes:
        if not isinstance(box,list):flow.fail("笔记排除框格式无效", "INVALID_NOTE_BOX", 422)
        imaging.bounds(box,*image.size)
    groups={**state.data.get("note_filters",{}).get("pages",{}),str(index):boxes}
    combined=[]
    for page_index,local_boxes in groups.items():
        frame=pages[int(page_index)]["box"]
        combined.extend([[frame[0]+box[0]*(frame[2]-frame[0]),frame[1]+box[1]*(frame[3]-frame[1]),frame[0]+box[2]*(frame[2]-frame[0]),frame[1]+box[3]*(frame[3]-frame[1])] for box in local_boxes])
    if len(combined)>64:flow.fail("同题笔记排除框最多64个", "INVALID_NOTE_BOX", 422)
    state.data={**state.data,"note_filters":{"source_asset_id":q.source_asset_id,"pages":groups,"boxes":combined},"recognition_draft":None}
    if not ai.recognition_available(db):flow.fail("识别尚未准备好，请查看设置", "OCR_NOT_READY", 409)
    state.data={**state.data,"recognition":"queued"}
    db.commit();schedule(background, recognize_background,qid,q.source_asset_id,True)
    return question(qid,db=db)


@router.post("/questions/{qid}/recognize")
def retry_recognize(
    qid: str, background: BackgroundTasks, body: dict | None = None, db: Session = Depends(get_db)
):
    q = flow.get_question(db, qid)
    s = flow.state_for(db, qid)
    if not q.source_asset_id:
        flow.fail("这道题没有图片")
    if not ai.recognition_available(db):
        flow.fail("识别尚未准备好，请查看设置中的图片识别状态")
    if s.data.get("recognition") in ("running", "queued"):
        flow.fail("图片正在识别，请稍候")
    source_kind = (body or {}).get("source", "original")
    if source_kind not in ("original", "processed"):
        flow.fail("请选择原图或整页处理稿，打印裁图不能用于提取完整题干")
    aid = q.source_asset_id if source_kind == "original" else s.data.get("processed_asset_id")
    if not aid:
        flow.fail("请先保存整页处理稿")
    s.data = {**s.data, "recognition": "queued"}
    db.commit()
    schedule(background, recognize_background, qid, aid, True)
    return {"queued": True}


@router.post("/questions/{qid}/recognition/use-draft")
def use_recognition_draft(qid: str, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    s = flow.state_for(db, qid)
    if s.data.get("recognition") in ("queued", "running"):
        flow.fail("请等待识别完成", "IMAGE_BUSY", 409)
    draft = s.data.get("recognition_draft")
    if not draft:
        flow.fail("暂无待采用的识别草稿")
    if s.data.get("recognition_draft_note_filters",{}) != s.data.get("note_filters",{}):
        flow.fail("笔记排除范围已变化，请重新识别后采用", "STALE_RECOGNITION", 409)
    if s.data.get("recognition_draft_version") != q.current_version_id:
        flow.fail("草稿生成后题目已修改，请重新提取，避免覆盖新内容", "STALE_RECOGNITION", 409)
    aid = s.data.get("recognition_draft_source")
    if not aid or aid not in (q.source_asset_id, s.data.get("processed_asset_id")):
        flow.fail("处理稿已修改，请从当前副本重新提取文字", "STALE_RECOGNITION", 409)
    output = ai.Recognition.model_validate(draft)
    from app.api.v1.image_edit import remember
    config = ai.recognition_configuration(db)
    processed = imaging.process_question(db, aid, output,
        config["ink"] if aid == q.source_asset_id else "off",
        config["pencil"] if aid == q.source_asset_id else "off", boxes_for(q,s))
    remember(s)
    content = {**output.model_dump(include={"stem", "options", "has_diagram", "diagram_regions", "handwriting_regions", "concerns", "inline_regions", "formula_audit"}),'inline_images':processed.get('inline_images',[])}
    question_service().update(db, q, {"content": content})
    s.data = {**s.data, **processed, "recognition": "completed", "recognition_draft": None,
        "recognition_note": "；".join(output.concerns + processed.get("image_processing_concerns", [])),
        "print_parts": None, "print_source_asset_id": None,
        "image_diagram_regions": [r.model_dump() for r in output.diagram_regions], "image_geometry_version_id": q.current_version_id}
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/analysis")
async def analyze_question(qid: str, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    starting_version = q.current_version_id
    pages = flow.state_for(db, qid).data.get("source_pages", [])
    if len(pages) > 1:
        output = await ai.analyze(db, flow.question_content(db, q), pages[0]["asset_id"], extra_aids=[page["asset_id"] for page in pages[1:]])
    else:
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
    from app.api.v1.image_edit import crop
    return crop(qid, body, db)


@router.post("/questions/{qid}/error")
def manual_error(qid: str, body: dict, db: Session = Depends(get_db)):
    flow.sync(db)
    day = checked_day(body.get("day", flow.today()))
    if day > flow.today():
        flow.fail("错题日期不能在未来")
    flow.mark_error(db, qid, day, f"manual:{qid}:{day}", awaiting_correction=True)
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/correct")
def confirm_correction(qid: str, db: Session = Depends(get_db)):
    flow.confirm_correction(db, qid)
    return question(qid, db=db)


@router.get("/corrections")
def pending_corrections(subject: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    if subject and subject not in flow.SUBJECTS:
        flow.fail("请选择数学、物理、化学或生物")
    grouped = select(Occurrence.question_id.label("qid"), Question.subject.label("subject"),
        func.min(Occurrence.upload_date).label("recorded_day"), func.count().label("occurrence_count")).join(
        Question, Question.id == Occurrence.question_id).where(
        Occurrence.status == "awaiting_correction", Question.status.notin_(["deleted", "draft"])).group_by(Occurrence.question_id, Question.subject).subquery()
    counts = {s: 0 for s in flow.SUBJECTS}
    for s, count in db.execute(select(grouped.c.subject, func.count()).group_by(grouped.c.subject)):
        counts[s] = count
    stmt = select(grouped)
    if subject:
        stmt = stmt.where(grouped.c.subject == subject)
    items = []
    for row in db.execute(stmt.order_by(grouped.c.recorded_day, grouped.c.qid).offset(offset).limit(limit)):
        q = flow.get_question(db, row.qid)
        items.append({"question_id": q.id, "subject": q.subject, "title": flow.question_content(db, q).get("stem", "")[:180] or "图片题目",
            "recorded_day": row.recorded_day, "recorded_label": flow.label(row.recorded_day), "occurrence_count": row.occurrence_count})
    return {"items": items, "counts": counts, "total": counts[subject] if subject else sum(counts.values()), "offset": offset, "limit": limit}


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
    if e.kind not in ("type", "error", "paper") or e.status != "open":
        flow.fail("该推送无法继续回收")
    aid = body.get("asset_id")
    if not db.get(Asset, aid):
        flow.fail("请选择已上传的作答图片")
    e.data = {**e.data, "started_day": e.data.get("started_day", flow.today()), "return_assets": [*e.data.get("return_assets", []), aid]}
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
