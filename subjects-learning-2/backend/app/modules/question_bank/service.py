"""One query contract for the bank and knowledge-tree pools."""
import json
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import String, Text, exists, func, or_, select, true
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.models import KnowledgeNode, Question
from app.db.session import Base
from app.modules.learning import service as flow
from app.modules.learning.models import QuestionState


class QuestionSearch(Base):
    __tablename__ = "question_search"
    question_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")


def subtree(db, nid):
    nodes = db.scalars(select(KnowledgeNode).where(KnowledgeNode.status == "active")).all()
    result = {nid}
    while True:
        extended = result | {n.id for n in nodes if n.parent_id in result}
        if extended == result:
            return result
        result = extended


def index_changes(db):
    rows = db.execute(select(Question, QuestionSearch).outerjoin(
        QuestionSearch, QuestionSearch.question_id == Question.id
    ).where(Question.status != "deleted", or_(
        QuestionSearch.question_id.is_(None),
        QuestionSearch.version_id != Question.current_version_id,
    ))).all()
    for q, entry in rows:
        if entry is None:
            entry = QuestionSearch(question_id=q.id)
            db.add(entry)
        entry.version_id = q.current_version_id
        entry.body = json.dumps(flow.question_content(db, q), ensure_ascii=False)
    db.flush()


def tagged(column, value):
    values = func.json_each(column).table_valued("value")
    return exists(select(1).select_from(values).where(values.c.value == value))


def search_values(column, pattern):
    values = func.json_each(column).table_valued("value")
    return exists(select(1).select_from(values).where(values.c.value.ilike(pattern, escape="\\")))


def list_questions(db: Session, *, subject="", q="", filter="", topic_ids=None,
                   topic_id="", knowledge_id="", tags=None, tag="", tag_mode="all",
                   untagged=False, issues_only=False, direct_topic=False,
                   date_from="", date_to="", offset=0, limit=50):
    index_changes(db)
    for value in (date_from, date_to):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                flow.fail("日期格式不正确")
    if date_from and date_to and date_from > date_to:
        flow.fail("开始日期不能晚于结束日期")
    if tag_mode not in ("all", "any"):
        flow.fail("标签匹配方式不正确")
    stmt = select(Question).outerjoin(QuestionState, QuestionState.question_id == Question.id)
    stmt = stmt.where(Question.status == "draft" if filter == "draft" else Question.status.notin_(["deleted", "draft"]))
    if subject:
        stmt = stmt.where(Question.subject == subject)
    if topic_ids:
        nodes = db.scalars(select(KnowledgeNode).where(KnowledgeNode.id.in_(topic_ids))).all()
        if len(nodes) != len(set(topic_ids)) or any(n.kind != "type" or n.status != "active" for n in nodes):
            flow.fail("请选择有效的叶子题型")
        for n in nodes:
            if db.scalar(select(KnowledgeNode.id).where(KnowledgeNode.parent_id == n.id, KnowledgeNode.status == "active")):
                flow.fail("多选题型只能选择叶节点")
        stmt = stmt.where(QuestionState.topic_id.in_(topic_ids))
    elif topic_id:
        stmt = stmt.where(QuestionState.topic_id.in_({topic_id} if direct_topic else subtree(db, topic_id)))
    if knowledge_id:
        values = func.json_each(QuestionState.data, "$.knowledge_ids").table_valued("value")
        stmt = stmt.where(exists(select(1).select_from(values).where(values.c.value.in_(subtree(db, knowledge_id)))))
    if filter == "unmastered":
        stmt = stmt.where(QuestionState.ever_wrong.is_(True), QuestionState.mastered.is_(False))
    elif filter == "mastered":
        stmt = stmt.where(QuestionState.ever_wrong.is_(True), QuestionState.mastered.is_(True))
    elif filter == "ordinary":
        stmt = stmt.where(or_(QuestionState.ever_wrong.is_(False), QuestionState.question_id.is_(None)))
    elif filter == "unassigned":
        stmt = stmt.where(QuestionState.topic_id.is_(None))
    if issues_only:
        parents = select(KnowledgeNode.parent_id).where(KnowledgeNode.status == "active", KnowledgeNode.parent_id.is_not(None))
        stmt = stmt.where(QuestionState.topic_id.in_(parents))
    if date_from:
        lower = datetime.fromisoformat(date_from).replace(tzinfo=timezone(timedelta(hours=8))).astimezone(UTC)
        stmt = stmt.where(Question.created_at >= lower)
    if date_to:
        upper = (datetime.fromisoformat(date_to).replace(tzinfo=timezone(timedelta(hours=8))) + timedelta(days=1)).astimezone(UTC)
        stmt = stmt.where(Question.created_at < upper)
    if q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.join(QuestionSearch, QuestionSearch.question_id == Question.id).where(or_(
            QuestionSearch.body.ilike(pattern, escape="\\"), Question.question_type.ilike(pattern, escape="\\"),
            search_values(Question.tags_json, pattern), search_values(Question.knowledge_points_json, pattern), Question.subject.ilike(pattern, escape="\\"),
        ))
    base = stmt.with_only_columns(Question.id, Question.tags_json).subquery()
    base_total = db.scalar(select(func.count()).select_from(base))
    untagged_total = db.scalar(select(func.count()).select_from(base).where(func.json_array_length(base.c.tags_json) == 0))
    values = func.json_each(base.c.tags_json).table_valued("value")
    facets = db.execute(select(values.c.value, func.count()).select_from(base).join(values, true()).group_by(values.c.value)).all()
    selected_tags = list(dict.fromkeys(tags or ([tag] if tag else [])))
    if untagged:
        stmt = stmt.where(func.json_array_length(Question.tags_json) == 0)
    elif selected_tags:
        clauses = [tagged(Question.tags_json, t) for t in selected_tags]
        stmt = stmt.where(or_(*clauses)) if tag_mode == "any" else stmt.where(*clauses)
    total = db.scalar(select(func.count()).select_from(stmt.with_only_columns(Question.id).subquery()))
    items = db.scalars(stmt.order_by(Question.created_at.desc(), Question.id).offset(max(0, offset)).limit(min(max(limit, 1), 500))).all()
    result = {"items": [flow.question_view(db, item) for item in items], "total": total,
              "base_total": base_total, "untagged_total": untagged_total,
              "tag_counts": [{"tag": t, "count": n} for t, n in facets]}
    db.commit()
    return result
