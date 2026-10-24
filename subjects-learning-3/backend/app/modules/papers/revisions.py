import copy
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base
from app.db.models import Question, QuestionVersion
from app.modules.learning import service as flow
from app.modules.learning.models import QuestionState, ReviewRound, RoundItem


class PaperRevision(Base):
    __tablename__ = "paper_revisions"
    __table_args__ = (UniqueConstraint("paper_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


def latest(db, paper):
    return db.scalar(select(PaperRevision).where(PaperRevision.paper_id == paper.id).order_by(PaperRevision.number.desc()))


def capture(db, paper, inputs=None):
    previous = latest(db, paper)
    options = {i["question_id"]: i for i in inputs or []}
    items = []
    for item in paper.items:
        q = db.get(Question, item.question_id)
        content = flow.question_content(db, q, item.question_version_id)
        state = db.get(QuestionState, q.id)
        answer = state.answer if state else content.get("answer", "")
        explanation = state.data.get("answer_explanation", "") if state else "\n".join(s.get("content", "") for s in content.get("solution_steps", []))
        config = options.get(q.id, {})
        data = {"stem": content.get("stem", ""), "content": content, "answer": answer,
                "answer_confirmed": state.answer_confirmed if state else bool(answer),
                "answer_explanation": explanation, "answer_asset_ids": state.data.get("answer_asset_ids", []) if state else [],
                "source_asset_id": q.source_asset_id, "crop_asset_id": state.data.get("crop_asset_id") if state else None,
                "inline_images": state.data.get("inline_images") or content.get("inline_images", []) if state else content.get("inline_images", []),
                "print_options_embedded": state.data.get("print_options_embedded", False) if state else False,
                "minutes": state.minutes if state else 8, "points": item.points, "section_name": item.section_name,
                "answer_space_mm": config.get("answer_space_mm", 30),
                "initial_state": {"ever_wrong": state.ever_wrong if state else False, "mastered": state.mastered if state else False}, "audit": []}
        if state and item.question_version_id != q.current_version_id:
            # A historical version must not silently borrow today's answer or crop.
            data.update(answer=content.get("answer", ""), answer_confirmed=False,
                answer_explanation="\n".join(s.get("content", "") for s in content.get("solution_steps", [])),
                answer_asset_ids=[], crop_asset_id=None, inline_images=content.get("inline_images", []))
        items.append({"question_id": q.id, "version_id": item.question_version_id, "data": data})
    exports = {} if previous else {key: aid for key, aid in (("student", paper.student_pdf_asset_id), ("answers", paper.answer_pdf_asset_id)) if aid}
    revision = PaperRevision(paper_id=paper.id, number=previous.number + 1 if previous else 1,
                             data={"title": paper.title, "subject": paper.subject, "items": items, "exports": exports})
    db.add(revision)
    db.flush()
    return revision


def view(db, paper):
    revision = latest(db, paper)
    if not revision:
        revision = capture(db, paper)
        db.commit()
    history = db.scalars(select(PaperRevision).where(PaperRevision.paper_id == paper.id).order_by(PaperRevision.number.desc())).all()
    return {"revision_id": revision.id, "revision": revision.number, "snapshot": revision.data,
            "revisions": [{"id": r.id, "number": r.number, "exports": r.data.get("exports", {})} for r in history]}


def schedule(db, paper, revision, day):
    if day < flow.today():
        flow.fail("试卷计划日期不能在过去")
    existing = db.scalar(select(ReviewRound).where(ReviewRound.kind == "paper", ReviewRound.data["revision_id"].as_string() == revision.id))
    if existing:
        return flow.round_view(db, existing.id)
    states = []
    for entry in revision.data["items"]:
        q = flow.get_question(db, entry["question_id"])
        if q.subject != paper.subject:
            flow.fail("加入学习计划的试卷须为同一学科")
        states.append(flow.state_for(db, q.id))
    if not states:
        flow.fail("空试卷不能加入学习计划")
    if any(e["data"]["minutes"] > flow.preferences(db)["daily_minutes"] * 1.2 for e in revision.data["items"]):
        flow.fail("本卷存在单题预计用时超过每日上限，请调整预算或重新编辑试卷用时后加入计划")
    review = flow.make_round(db, "paper", paper.subject, day, day, states)
    review.data = {**review.data, "revision_id": revision.id}
    items = db.scalars(select(RoundItem).where(RoundItem.round_id == review.id).order_by(RoundItem.position)).all()
    for item, entry in zip(items, revision.data["items"]):
        item.version_id, item.data = entry["version_id"], copy.deepcopy(entry["data"])
    event = flow.get_event(db, items[0].event_id)
    event.title = revision.data["title"]
    event.minutes = sum(e["data"]["minutes"] for e in revision.data["items"])
    # Free papers reserve capacity in the same daily budget and split like review papers.
    other_minutes = sum(e.minutes for e in db.scalars(select(flow.LearningEvent).where(flow.LearningEvent.day == day, flow.LearningEvent.kind.in_(["error", "type", "paper"]), flow.LearningEvent.status.notin_(["abandoned", "paused"]), flow.LearningEvent.id != event.id)))
    flow.split_round(db, review, flow.preferences(db)["daily_minutes"] * 1.2, other_minutes, day)
    for event in db.scalars(select(flow.LearningEvent).where(flow.LearningEvent.key.like(f"round:{review.id}:%"))):
        event.title = f"{revision.data['title']} · 第{event.data['slice']}份"
    db.commit()
    return flow.round_view(db, review.id)
