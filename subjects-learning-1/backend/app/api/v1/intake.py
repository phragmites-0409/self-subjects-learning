"""Complete a staged intake without exposing unfinished questions to scheduling."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.learning import checked_day, question
from app.db.models import KnowledgeNode
from app.db.session import get_db
from app.modules.learning import ai, imaging
from app.modules.learning import service as flow

router = APIRouter(prefix="/learning")


def supplied_answer(
    db, qid, answer="", explanation="", assets=None, source="manual", reference=None
):
    flow.get_question(db, qid)
    state = flow.state_for(db, qid)
    state.answer = str(answer).strip()
    state.answer_confirmed = True
    state.data = {
        **state.data,
        "answer_source": source,
        "answer_explanation": str(explanation).strip(),
        "answer_asset_ids": assets or [],
        "answer_reference": reference or {},
    }
    db.commit()


@router.post("/questions/{qid}/answer")
async def answer(qid: str, body: dict, db: Session = Depends(get_db)):
    flow.get_question(db, qid)
    if body.get("source", "manual") != "manual":
        flow.fail("请选择手动输入或拍照；其他来源请使用对应入口")
    text = str(body.get("answer", "")).strip()
    explanation = str(body.get("explanation", "")).strip()
    aid = body.get("asset_id")
    if not text and not explanation and not aid:
        flow.fail("请填写答案内容或上传答案照片")
    note = ""
    if aid:
        imaging.load_image(db, aid)
        if ai.public_configuration(db)["configured"]:
            try:
                output = await ai.read_answer(db, aid)
                text = text or output.answer
                explanation = explanation or output.explanation
                note = "；".join(output.concerns)
            except Exception as exc:  # noqa: BLE001 - Retain user-supplied photo even when OCR fails.
                note = f"答案照片已保存，文字转录失败：{str(exc)[:300]}"
    supplied_answer(db, qid, text, explanation, [aid] if aid else [])
    state = flow.state_for(db, qid)
    state.data = {**state.data, "answer_note": note}
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/answer/use-ai")
def use_ai(qid: str, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    state = flow.state_for(db, qid)
    output = state.data.get("analysis", {})
    if state.data.get("analysis_version") != q.current_version_id:
        flow.fail("题面已修改，请重新请求AI解析", "STALE_ANALYSIS", 409)
    if (
        not output.get("answer_draft", "").strip()
        or not output.get("explanation", "").strip()
    ):
        flow.fail("请先请求AI生成完整的答案和解析")
    state.answer = output["answer_draft"]
    state.answer_confirmed = False
    state.data = {
        **state.data,
        "answer_source": "ai",
        "answer_explanation": output["explanation"],
        "answer_asset_ids": [],
        "answer_reference": {},
        "answer_note": "",
    }
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/archive")
def archive(qid: str, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    if q.status != "draft":
        return question(qid, db=db)
    state = flow.state_for(db, qid)
    if state.data.get("recognition") in ("queued", "running"):
        flow.fail("题目正在识别，请稍后入库", "INTAKE_INCOMPLETE", 409)
    if q.subject in flow.SUBJECTS:
        node = db.get(KnowledgeNode, state.topic_id) if state.topic_id else None
        if (
            not node
            or node.kind != "type"
            or node.subject != q.subject
            or node.status != "active"
            or db.scalar(
                select(KnowledgeNode).where(
                    KnowledgeNode.parent_id == node.id, KnowledgeNode.status == "active"
                )
            )
        ):
            flow.fail("正式入库前必须选择当前学科的叶子题型", "INTAKE_INCOMPLETE", 409)
    if not (
        state.answer.strip()
        or state.data.get("answer_explanation", "").strip()
        or state.data.get("answer_asset_ids")
    ):
        flow.fail("正式入库前请补充答案内容", "INTAKE_INCOMPLETE", 409)
    if state.data.get("answer_source") == "ai" and (
        not state.answer_confirmed
        or not state.answer.strip()
        or not state.data.get("answer_explanation", "").strip()
    ):
        flow.fail("AI答案与解析需要人工确认后入库", "ANSWER_NOT_CONFIRMED", 409)
    content = flow.question_content(db, q)
    if not content.get("stem", "").strip() and not q.source_asset_id:
        flow.fail("请填写题干或上传题目照片")
    if content.get("has_diagram") and not state.data.get("crop_asset_id"):
        flow.fail(
            "示意图尚未分离，请完成自动识别或手动框选打印图像", "DIAGRAM_MISSING", 409
        )
    q.status = "approved"
    if state.data.get("answer_source") != "ai":
        state.answer_confirmed = True
    state.data = {**state.data, "archived_day": flow.today()}
    if state.data.get("pending_error"):
        day = checked_day(state.data.get("intake_day", flow.today()))
        flow.mark_error(db, qid, day, f"intake:{qid}")
    flow.activate_topics(db, flow.today())
    db.commit()
    return question(qid, db=db)


@router.post("/questions/{qid}/estimate")
async def estimate(qid: str, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    starting_version = q.current_version_id
    output = await ai.estimate_time(db, flow.question_content(db, q), q.source_asset_id)
    db.refresh(q)
    if q.current_version_id != starting_version:
        flow.fail("预估期间题面已修改，请重试", "STALE_ESTIMATE", 409)
    state = flow.state_for(db, qid)
    state.data = {**state.data, "time_estimate": output.model_dump()}
    db.commit()
    return question(qid, db=db)
