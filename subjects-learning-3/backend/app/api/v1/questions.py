from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.account_scope import account_id
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Question
from app.db.session import get_db
from app.modules.jobs.service import create_job, fail_job, finish_job
from app.modules.questions.schemas import ParseRequest, QuestionUpdate
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter()


def service() -> QuestionService:
    settings = get_settings()
    return QuestionService(LocalFilesystemContentStore(), AIGateway(DeepSeekProvider(settings), settings))


@router.get("")
def list_questions(subject: str = "", question_type: str = "", method: str = "", status: str = "", q: str = "", limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return service().list(db, q=q, subject=subject, question_type=question_type, method=method, status=status, limit=min(limit, 100), offset=max(offset, 0))


@router.get("/{question_id}")
def get_question(question_id: str, db: Session = Depends(get_db)):
    return service().detail(db, question_id)


@router.post("/{question_id}/parse")
async def parse_question(question_id: str, request: ParseRequest, db: Session = Depends(get_db)):
    question = db.get(Question, question_id)
    if not question:
        raise AppError("QUESTION_NOT_FOUND", "题目不存在", 404)
    job = create_job(db, "question_parse", {"question_id": question_id})
    try:
        _, result = await service().parse(db, question, request.text)
        finish_job(db, job, result)
        return {"job_id": job.id, "question": service().detail(db, question_id), **result}
    except AppError as exc:
        fail_job(db, job, exc.code)
        raise


@router.post("/{question_id}/approve")
def approve_question(question_id: str, db: Session = Depends(get_db)):
    question = db.get(Question, question_id)
    if not question:
        raise AppError("QUESTION_NOT_FOUND", "题目不存在", 404)
    return service().approve(db, question)


@router.patch("/{question_id}")
def update_question(question_id: str, changes: QuestionUpdate, db: Session = Depends(get_db)):
    question = db.get(Question, question_id)
    if not question:
        raise AppError("QUESTION_NOT_FOUND", "题目不存在", 404)
    return service().update(db, question, changes.model_dump(exclude_none=True))


@router.delete("/{question_id}")
def delete_question(question_id: str, db: Session = Depends(get_db)):
    question = db.get(Question, question_id)
    if not question:
        raise AppError("QUESTION_NOT_FOUND", "题目不存在", 404)
    if account_id() is not None:
        raise AppError("REPLICA_REQUIRED", "正式题目删除需先确认另一台在线设备已完成副本校验", 409)
    question.status = "deleted"
    db.commit()
    return {"id": question_id, "deleted": True}
