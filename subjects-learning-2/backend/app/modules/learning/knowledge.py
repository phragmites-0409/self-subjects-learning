"""Knowledge contents and classification diagnostics. Never creates question copies."""
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4
import json

from sqlalchemy import ForeignKey, Integer, JSON, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.db.session import Base
from app.db.models import Asset, KnowledgeNode, KnowledgeContent as LegacyKnowledgeContent, Question, Setting
from app.modules.learning.models import QuestionState
from app.modules.learning import service as flow
from app.storage.local_store import LocalFilesystemContentStore


class KnowledgeNodeContents(Base):
    __tablename__ = "learning_knowledge_contents"
    node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": revision}


DEFAULT_TAGS = {"note": ["方法", "模型", "公式", "学习材料", "易错点"], "question": ["重点题", "模板题", "难题"], "node": ["校外", "重点"]}
MATERIALS = ["主题分类", "主题词汇", "常用短语", "句型表达", "开头", "过渡", "结尾", "高级替换", "主题观点", "范文片段"]


def tags(value):
    if not isinstance(value, list) or len(value) > 500 or any(not isinstance(t, str) or len(t.strip()) > 100 for t in value):
        flow.fail("标签应为文字列表，每个标签最多100字")
    return list(dict.fromkeys(t.strip() for t in value if t.strip()))


def remember_tags(db, kind, values):
    if kind not in DEFAULT_TAGS:
        flow.fail("标签类别无效")
    row = db.get(Setting, "knowledge.tags." + kind)
    existing = json.loads(row.value) if row else []
    merged = tags(existing + tags(values))
    if not row:
        row = Setting(key="knowledge.tags." + kind)
        db.add(row)
    row.value = json.dumps(merged, ensure_ascii=False)


def tag_catalog(db):
    result = {}
    for kind, defaults in DEFAULT_TAGS.items():
        row = db.get(Setting, "knowledge.tags." + kind)
        result[kind] = defaults + (json.loads(row.value) if row else [])
    for row in db.scalars(select(KnowledgeNodeContents)):
        result["node"] += row.data.get("tags", [])
        for entry in row.data.get("note_entries", []):
            result["note"] += entry.get("tags", [])
    for q in db.scalars(select(Question).where(Question.status != "deleted")):
        result["question"] += q.tags_json or []
    for state in db.scalars(select(flow.TopicState)):
        result["node"] += state.data.get("tags", [])
    return {k: tags(v) for k, v in result.items()}


def content_for(db: Session, node: KnowledgeNode):
    row = db.get(KnowledgeNodeContents, node.id)
    if row:
        return row
    ts = flow.topic_state(db, node.id) if node.kind == "type" else None
    legacy = ts.data if ts else {}
    data = {"note_entries": [], "pain_entries": [], "tags": legacy.get("tags", []), "material_type": "主题分类"}
    for field, value, collection, title in [
        ("summary", node.summary, "note_entries", "原有正文"),
        ("method", legacy.get("method"), "note_entries", "解题思路"),
        ("notes", legacy.get("notes"), "note_entries", "学习笔记"),
        ("pain_points", legacy.get("pain_points"), "pain_entries", "待改进问题"),
    ]:
        if isinstance(value, str) and value.strip():
            data[collection].append({"id": "legacy-" + field, "title": title, "body": value, "tags": [], "images": [], "pinned": False, "source": "manual", "confirmed": True, "revision": 1})
    # Retain contents created through the older knowledge API too.
    for item in db.scalars(select(LegacyKnowledgeContent).where(LegacyKnowledgeContent.node_id == node.id)):
        from app.documents.content import loads_compressed
        try:
            raw = LocalFilesystemContentStore().read_bytes(item.content_storage_key)
            try:
                text = loads_compressed(raw)
                text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
            except (ValueError, OSError, UnicodeError):
                text = raw.decode("utf-8")
        except (OSError, UnicodeError):
            text = "原材料文件缺失，请从备份恢复。文件记录：" + item.content_storage_key
        if text.strip():
            data["note_entries"].append({"id": "legacy-content-" + item.id, "title": item.title[:100] or "原有材料", "body": text, "tags": [], "images": [], "pinned": False, "source": item.source if item.source in ("manual", "external", "ai") else "external", "confirmed": True, "revision": 1})
    row = KnowledgeNodeContents(node_id=node.id, data=data)
    db.add(row)
    db.flush()
    return row


def migrate_contents(db):
    for n in db.scalars(select(KnowledgeNode)):
        content_for(db, n)
    db.commit()


def active_children(db, nid):
    return db.scalars(select(KnowledgeNode).where(KnowledgeNode.parent_id == nid, KnowledgeNode.status == "active")).all()


def subtree(db, nid):
    nodes = db.scalars(select(KnowledgeNode).where(KnowledgeNode.status == "active")).all()
    found, queue = {nid}, [nid]
    while queue:
        current = queue.pop()
        for n in nodes:
            if n.parent_id == current and n.id not in found:
                found.add(n.id)
                queue.append(n.id)
    return found


def issue_questions(db, node):
    if node.kind != "type" or not active_children(db, node.id):
        return []
    return db.scalars(select(QuestionState).join(Question).where(QuestionState.topic_id == node.id, Question.status != "deleted")).all()


def topic_issue(db, tid):
    node = db.get(KnowledgeNode, tid) if tid else None
    return bool(node and node.kind == "type" and active_children(db, tid))


def aggregate_mastery(db, node):
    rows = db.scalars(select(QuestionState).join(Question).where(QuestionState.topic_id.in_(subtree(db, node.id)), Question.status.notin_(["deleted", "draft"]))).all()
    wrong = [s for s in rows if s.ever_wrong and not s.data.get("correction_only")]
    passed = sum(s.mastered for s in wrong)
    return {"total": len(wrong), "mastered": passed, "ratio": round(passed * 100 / len(wrong), 2) if wrong else None, "pool": len(rows)}


def save_entry(db, node, collection, body, eid=None):
    if collection not in ("note_entries", "pain_entries"):
        flow.fail("条目分类无效")
    row = content_for(db, node)
    data = deepcopy(row.data)
    items = data[collection]
    current = next((e for e in items if e["id"] == eid), None) if eid else None
    if eid and not current:
        flow.fail("条目不存在", status=404)
    if current and body.get("revision") != current["revision"]:
        flow.fail("条目已在其他页面修改，请关闭编辑并重新打开", "STALE_ENTRY", 409)
    title, text = body.get("title", ""), body.get("body", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or not isinstance(text, str):
        flow.fail("请填写标题（1至100字）和有效正文")
    source = body.get("source", "manual")
    if source not in ("manual", "external", "ai") or (source != "manual" and body.get("confirmed") is not True):
        flow.fail("外部或AI内容需校对并确认收录")
    if not isinstance(body.get("pinned", False), bool):
        flow.fail("置顶状态无效")
    images = body.get("images", [])
    if not isinstance(images, list) or len(images) > 100 or (collection == "pain_entries" and images):
        flow.fail("图片列表无效")
    if not text.strip() and not images:
        flow.fail("请填写正文或上传笔记图片")
    verified, ids = [], set()
    for image in images:
        if not isinstance(image, dict):
            flow.fail("原图记录无效")
        aid, name = image.get("id"), image.get("name")
        asset = db.get(Asset, aid) if isinstance(aid, str) else None
        if not asset or asset.kind != "knowledge_original" or asset.deleted_at or aid in ids or not isinstance(name, str) or not name.strip():
            flow.fail("原图不存在、重复或不是笔记原图")
        if not LocalFilesystemContentStore().path_for(asset.storage_key).is_file():
            flow.fail("原图文件缺失，未保存笔记")
        ids.add(aid)
        verified.append({"id": aid, "name": name[:255], "type": asset.mime_type, "size": asset.byte_size, "sha256": asset.sha256})
    entry = {"id": eid or str(uuid4()), "title": title.strip(), "body": text, "tags": tags(body.get("tags", [])), "images": verified, "pinned": body.get("pinned", False), "source": source, "confirmed": True, "revision": current["revision"] + 1 if current else 1, "updated_at": datetime.now(UTC).isoformat()}
    if current:
        items[items.index(current)] = entry
    else:
        if len(items) >= 500:
            flow.fail("该节点条目已达500条")
        items.append(entry)
    remember_tags(db, "note", tags(body.get("tag_options", [])) + entry["tags"])
    row.data = data
    return entry


def reassign(db, node, assignments):
    if not isinstance(assignments, dict) or not assignments:
        flow.fail("请至少选择一道题的新归属")
    direct = {s.question_id: s for s in issue_questions(db, node)}
    changes = []
    for qid, dest in assignments.items():
        state = direct.get(qid)
        target = db.get(KnowledgeNode, dest) if isinstance(dest, str) else None
        if not state or not target or target.status != "active" or target.subject != node.subject or target.kind != "type" or active_children(db, target.id):
            flow.fail("只能将本节点直接挂题调整到同学科叶子题型")
        changes.append((state, target))
    for state, target in changes:
        state.topic_id = target.id
        db.get(Question, state.question_id).question_type = target.name
    db.flush()
    # Existing rounds, occurrences, snapshots and answers are deliberately untouched.
    return len(issue_questions(db, node))
