from __future__ import annotations

from sqlalchemy import desc, exists, func, or_, select
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.core.errors import AppError
from app.db.models import Asset, Question, QuestionVersion
from app.documents.content import dumps_compressed, loads_compressed
from app.storage.local_store import LocalFilesystemContentStore


class QuestionService:
    def __init__(self, store: LocalFilesystemContentStore, gateway: AIGateway):
        self.store = store
        self.gateway = gateway

    def _version_content(self, version: QuestionVersion) -> dict:
        try:
            return loads_compressed(self.store.read_bytes(version.content_storage_key))
        except (FileNotFoundError, ValueError) as exc:
            raise AppError("CONTENT_MISSING", "题目内容文件不存在或已损坏", 500) from exc

    def create_from_asset(self, db: Session, asset: Asset, text: str = "") -> Question:
        question = Question(source_asset_id=asset.id, status="draft")
        db.add(question)
        db.commit()
        db.refresh(question)
        self.update(db, question, {"content": {"stem": text, "options": [], "uncertainty_notes": ["原图已保存，文字待核对"]}})
        return question

    async def parse(self, db: Session, question: Question, text: str = "") -> tuple[Question, dict]:
        is_draft = question.status == "draft"
        if not question.source_asset_id:
            raise AppError("QUESTION_SOURCE_MISSING", "题目缺少图片来源", 400)
        asset = db.get(Asset, question.source_asset_id)
        image = self.store.read_bytes(asset.storage_key) if asset else None
        preflight = await self.gateway.preflight(text, image)
        if preflight.decision != "ready":
            question.status = "draft" if is_draft else "needs_review"
            db.commit()
            return question, {"stage": "preflight", "preflight": preflight.model_dump(), "accepted": False}

        content = await self.gateway.parse_question(text or preflight.recognized_text, image)
        review = await self.gateway.review_question(content)
        payload = {"content": content.model_dump(), "preflight": preflight.model_dump(), "review": review.model_dump()}
        compressed, digest = self._store_content(payload)
        version_number = len(question.versions) + 1
        version = QuestionVersion(
            question_id=question.id,
            version_number=version_number,
            content_storage_key=compressed,
            content_sha256=digest,
            source="ai",
            validation_status="valid",
            review_status=review.status,
        )
        db.add(version)
        db.flush()
        question.current_version_id = version.id
        question.subject = content.subject
        question.grade = content.grade
        question.question_type = content.question_type
        question.difficulty = content.difficulty
        question.methods_json = content.methods
        question.knowledge_points_json = content.knowledge_points
        question.status = "draft" if is_draft else ("approved" if review.status == "pass" else "needs_review")
        db.commit()
        db.refresh(question)
        return question, {"stage": "completed", "preflight": preflight.model_dump(), "review": review.model_dump(), "content": content.model_dump(), "accepted": True}

    def _store_content(self, payload: dict) -> tuple[str, str]:
        return self.store.put_bytes("structured-content", dumps_compressed(payload), ".json.gz")

    def detail(self, db: Session, question_id: str) -> dict:
        question = db.get(Question, question_id)
        if not question or question.status == "deleted":
            raise AppError("QUESTION_NOT_FOUND", "题目不存在", 404)
        version = db.get(QuestionVersion, question.current_version_id) if question.current_version_id else None
        content = self._version_content(version) if version else {}
        return self.serialize(question, version, content)

    @staticmethod
    def serialize(question: Question, version: QuestionVersion | None, payload: dict) -> dict:
        content = payload.get("content", payload) if payload else {}
        return {
            "id": question.id,
            "status": question.status,
            "subject": question.subject,
            "grade": question.grade,
            "question_type": question.question_type,
            "difficulty": question.difficulty,
            "methods": question.methods_json or [],
            "knowledge_points": question.knowledge_points_json or [],
            "tags": question.tags_json or [],
            "created_at": question.created_at,
            "updated_at": question.updated_at,
            "version_id": version.id if version else None,
            "version_number": version.version_number if version else None,
            "content": content,
            "preflight": payload.get("preflight", {}) if payload else {},
            "review": payload.get("review", {}) if payload else {},
        }

    def list(self, db: Session, q: str = "", subject: str = "", question_type: str = "", method: str = "", status: str = "", limit: int = 50, offset: int = 0) -> dict:
        stmt = select(Question).where(Question.status != "deleted").order_by(desc(Question.updated_at)).limit(limit).offset(offset)
        if status != "draft":
            stmt = stmt.where(Question.status != "draft")
        if subject:
            stmt = stmt.where(Question.subject == subject)
        if question_type:
            stmt = stmt.where(Question.question_type == question_type)
        if status:
            stmt = stmt.where(Question.status == status)
        if method:
            methods = func.json_each(Question.methods_json).table_valued("value")
            stmt = stmt.where(exists(select(1).select_from(methods).where(methods.c.value == method)))
        if q:
            pattern = f"%{q}%"
            methods = func.json_each(Question.methods_json).table_valued("value")
            knowledge_points = func.json_each(Question.knowledge_points_json).table_valued("value")
            stmt = stmt.where(
                or_(
                    Question.subject.like(pattern),
                    Question.question_type.like(pattern),
                    exists(select(1).select_from(methods).where(methods.c.value.like(pattern))),
                    exists(select(1).select_from(knowledge_points).where(knowledge_points.c.value.like(pattern))),
                )
            )
        items = db.scalars(stmt).all()
        return {"items": [self.detail(db, item.id) for item in items], "limit": limit, "offset": offset, "has_more": len(items) == limit}

    def update(self, db: Session, question: Question, changes: dict) -> dict:
        is_draft = question.status == "draft"
        detail = self.detail(db, question.id)
        content = detail.get("content", {})
        content.update(changes.get("content", {}))
        for field in ("subject", "grade", "question_type", "difficulty", "methods", "knowledge_points", "tags"):
            if field in changes:
                setattr(question, "methods_json" if field == "methods" else "knowledge_points_json" if field == "knowledge_points" else "tags_json" if field == "tags" else field, changes[field])
        compressed, digest = self._store_content({"content": content, "preflight": detail.get("preflight", {}), "review": {"status": "user_edited"}})
        latest = max((version.version_number for version in question.versions), default=0)
        version = QuestionVersion(question_id=question.id, version_number=latest + 1, content_storage_key=compressed, content_sha256=digest, source="user", validation_status="valid", review_status="pending")
        db.add(version)
        db.flush()
        question.current_version_id = version.id
        question.status = "draft" if is_draft else "approved"
        db.commit()
        return self.detail(db, question.id)

    def approve(self, db: Session, question: Question) -> dict:
        if question.status == "draft":
            raise AppError("INTAKE_INCOMPLETE", "请在录入流程中补充答案并选择题型后正式入库", 409)
        question.status = "approved"
        version = db.get(QuestionVersion, question.current_version_id) if question.current_version_id else None
        if version:
            version.review_status = "user_approved"
        db.commit()
        return self.detail(db, question.id)
