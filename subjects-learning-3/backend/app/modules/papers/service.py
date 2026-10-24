from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Asset, Paper, PaperItem, Question, QuestionVersion
from app.documents.content import loads_compressed
from app.documents.pdf_service import generate_paper_pdf
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore


class PaperService:
    def __init__(self, store: LocalFilesystemContentStore, settings: Settings, questions: QuestionService):
        self.store = store
        self.settings = settings
        self.questions = questions

    def list(self, db: Session) -> list[dict]:
        return [self.serialize(db, paper) for paper in db.scalars(select(Paper).order_by(Paper.updated_at.desc())).all()]

    def get(self, db: Session, paper_id: str) -> dict:
        paper = db.get(Paper, paper_id)
        if not paper:
            raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
        return self.serialize(db, paper)

    def create(self, db: Session, title: str, subject: str, grade: str, items: list[dict]) -> dict:
        if not title.strip():
            raise AppError("INVALID_PAPER", "试卷名称不能为空", 422)
        if subject == "高中综合" and items:
            first = db.get(Question, items[0].get("question_id"))
            subject = first.subject if first else subject
        paper = Paper(title=title.strip(), subject=subject, grade=grade)
        db.add(paper)
        db.flush()
        self._replace_items(db, paper, items)
        from .revisions import capture
        capture(db, paper, items)
        db.commit()
        return self.serialize(db, paper)

    def update(self, db: Session, paper: Paper, changes: dict) -> dict:
        for field in ("title", "subject", "grade"):
            if field in changes:
                setattr(paper, field, changes[field])
        if "items" in changes:
            self._replace_items(db, paper, changes["items"])
        from .revisions import capture
        capture(db, paper, changes.get("items"))
        db.commit()
        return self.serialize(db, paper)

    def _replace_items(self, db: Session, paper: Paper, items: list[dict]) -> None:
        if len({i.get("question_id") for i in items}) != len(items):
            raise AppError("PAPER_DUPLICATE", "一份试卷中不能重复选择同一道题", 422)
        paper.items.clear()
        total = 0.0
        for position, raw in enumerate(items):
            question = db.get(Question, raw.get("question_id"))
            if not question or question.status in ("deleted", "draft") or not question.current_version_id:
                raise AppError("PAPER_QUESTION_INVALID", "试卷包含不存在或未确认的题目", 422, {"question_id": raw.get("question_id")})
            if question.subject != paper.subject:
                raise AppError("PAPER_SUBJECT_INVALID", "一份试卷中的题目须属于所选学科", 422)
            version_id = raw.get("question_version_id") or question.current_version_id
            version = db.get(QuestionVersion, version_id)
            if not version or version.question_id != question.id:
                raise AppError("PAPER_VERSION_INVALID", "题目版本不存在或不属于该题目", 422)
            points = float(raw.get("points", 5))
            total += points
            paper.items.append(PaperItem(question_id=question.id, question_version_id=version_id, position=position, points=points, section_name=raw.get("section_name", "基础题")))
        paper.total_points = total

    def serialize(self, db: Session, paper: Paper) -> dict:
        return {"id": paper.id, "title": paper.title, "subject": paper.subject, "grade": paper.grade, "total_points": paper.total_points, "status": paper.status, "student_pdf_asset_id": paper.student_pdf_asset_id, "answer_pdf_asset_id": paper.answer_pdf_asset_id, "created_at": paper.created_at, "updated_at": paper.updated_at, "items": [{"id": item.id, "question_id": item.question_id, "question_version_id": item.question_version_id, "position": item.position, "points": item.points, "section_name": item.section_name} for item in paper.items]}

    def export(self, db: Session, paper: Paper, include_answers: bool) -> dict:
        items = []
        for item in paper.items:
            version = db.get(QuestionVersion, item.question_version_id)
            if not version:
                raise AppError("PAPER_VERSION_INVALID", "试卷题目版本不存在", 500)
            payload = loads_compressed(self.store.read_bytes(version.content_storage_key))
            items.append({"content": payload.get("content", {}), "points": item.points})
        from app.core.account_scope import active_data_dir

        target = active_data_dir() / "tmp" / f"paper-{paper.id}-{'answers' if include_answers else 'student'}.pdf"
        generate_paper_pdf(paper.title, items, target, include_answers=include_answers)
        data = target.read_bytes()
        storage_key, digest = self.store.put_bytes("generated-pdfs", data, ".pdf")
        asset = Asset(kind="generated_pdf", storage_key=storage_key, sha256=digest, mime_type="application/pdf", byte_size=len(data))
        db.add(asset)
        db.flush()
        if include_answers:
            paper.answer_pdf_asset_id = asset.id
        else:
            paper.student_pdf_asset_id = asset.id
        paper.status = "generated"
        db.commit()
        target.unlink(missing_ok=True)
        return {"paper": self.serialize(db, paper), "asset_id": asset.id, "download_url": f"/api/v1/assets/{asset.id}/download"}
