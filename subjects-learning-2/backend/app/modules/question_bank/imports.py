"""Preview text question imports; incomplete records remain drafts."""
import json
from uuid import uuid4
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import KnowledgeNode, Question, QuestionVersion
from app.db.session import Base
from app.documents.content import dumps_compressed
from app.modules.learning import service as flow
from app.storage.local_store import LocalFilesystemContentStore


class QuestionImport(Base):
    __tablename__ = "question_bank_imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    data: Mapped[dict] = mapped_column(JSON)


def preview(db, text):
    try:
        parsed = json.loads(text)
        rows = parsed.get("questions", []) if isinstance(parsed, dict) else parsed
        if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
            raise ValueError()
    except (ValueError, TypeError):
        flow.fail("请提供1–500条题目的JSON数组，或包含questions数组的对象")
    valid, errors = [], []
    for n, raw in enumerate(rows, 1):
        try:
            if not isinstance(raw, dict):
                raise ValueError("题目须为对象")
            subject, stem = str(raw.get("subject", "")).strip(), str(raw.get("stem", "")).strip()
            if subject not in flow.ALL_SUBJECTS or not stem or len(stem) > 30000:
                raise ValueError("学科须为六科之一，题干不能为空或超过30000字")
            tags, options = raw.get("tags", []), raw.get("options", [])
            if any(not isinstance(x, list) or any(not isinstance(s, str) for s in x) for x in (tags, options)):
                raise ValueError("标签和选项须为文字数组")
            if "[[图块:" in stem or raw.get("has_diagram") or raw.get("inline_images"):
                raise ValueError("含图题请通过拍题录入，保留原图和校对流程")
            minutes = raw.get("minutes", 8)
            if type(minutes) not in (int, float) or not 0.5 <= minutes <= 120:
                raise ValueError("预计用时应为0.5–120分钟")
            tid = raw.get("topic_id") or None
            if tid:
                node = db.get(KnowledgeNode, tid)
                if not node or node.subject != subject or node.kind != "type" or node.status != "active" or db.scalar(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == tid, KnowledgeNode.status == "active")):
                    raise ValueError("题型ID须为本学科的有效叶子节点")
            answer, explanation = str(raw.get("answer", "")).strip(), str(raw.get("explanation", "")).strip()
            complete = bool(answer or explanation) and (subject not in flow.SUBJECTS or bool(tid))
            valid.append({"subject": subject, "stem": stem, "options": options, "tags": list(dict.fromkeys(t.strip() for t in tags if t.strip())),
                          "topic_id": tid, "minutes": minutes, "answer": answer, "explanation": explanation,
                          "action": "可正式入库" if complete else "草稿待补全", "complete": complete})
        except (ValueError, TypeError) as exc:
            errors.append({"line": n, "error": str(exc)})
    batch = QuestionImport(data={"items": valid, "errors": errors})
    db.add(batch); db.commit()
    return {"id": batch.id, **batch.data}


def confirm(db, iid, approved):
    batch = db.get(QuestionImport, iid)
    if not batch:
        flow.fail("导入预览不存在", status=404)
    if "result" in batch.data:
        return batch.data["result"]
    ids = []
    for raw in batch.data["items"]:
        q = Question(subject=raw["subject"], status="approved" if approved and raw["complete"] else "draft", tags_json=raw["tags"])
        db.add(q); db.flush()
        content = {"stem": raw["stem"], "options": raw["options"], "has_diagram": False}
        key, digest = LocalFilesystemContentStore().put_bytes("structured-content", dumps_compressed({"content": content}), ".json.gz")
        version = QuestionVersion(question_id=q.id, version_number=1, content_storage_key=key, content_sha256=digest, source="user", validation_status="valid", review_status="pass")
        db.add(version); db.flush(); q.current_version_id = version.id
        state = flow.state_for(db, q.id)
        state.topic_id, state.minutes, state.answer, state.answer_confirmed = raw["topic_id"], raw["minutes"], raw["answer"], approved
        state.data = {"answer_source": "manual", "answer_explanation": raw["explanation"], "recognition": "done", "subject_source": "manual", "intake_day": flow.today(), "import_id": iid}
        if state.topic_id:
            q.question_type = db.get(KnowledgeNode, state.topic_id).name
        ids.append({"id": q.id, "status": q.status})
    result = {"items": ids, "approved": sum(i["status"] == "approved" for i in ids), "drafts": sum(i["status"] == "draft" for i in ids)}
    batch.data = {**batch.data, "result": result}
    db.commit()
    return result
