"""Retain intake origin and apply a user's chosen, matching leaf category."""
from sqlalchemy import select

from app.db.models import KnowledgeNode
from app.modules.learning import service as flow


def normalize_context(value, day):
    if not isinstance(value, dict):
        return {"from": "capture", "day": day}
    context = {"from": value.get("from") if value.get("from") in ("knowledge", "plan") else "capture", "day": day}
    if value.get("subject") in flow.ALL_SUBJECTS:
        context["subject"] = value["subject"]
    if value.get("branch") in ("type", "knowledge", "record"):
        context["branch"] = value["branch"]
    if isinstance(value.get("node_id"), str) and len(value["node_id"]) <= 36:
        context["node_id"] = value["node_id"]
    return context


def apply_category(db, q, state):
    context = state.data.get("intake_context", {})
    if context.get("from") != "knowledge" or context.get("subject") != q.subject:
        return
    node = db.get(KnowledgeNode, context.get("node_id")) if context.get("node_id") else None
    if not node or node.subject != q.subject or node.status != "active":
        return
    if context.get("branch") == "type" and node.kind == "type" and not state.topic_id and not db.scalar(
        select(KnowledgeNode).where(KnowledgeNode.parent_id == node.id, KnowledgeNode.status == "active")
    ):
        state.topic_id = node.id
        q.question_type = node.name
    if context.get("branch") == "knowledge" and node.kind == "knowledge" and not state.data.get("knowledge_ids"):
        state.data = {**state.data, "knowledge_ids": [node.id]}
