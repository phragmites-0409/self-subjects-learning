from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.config import get_settings
from app.db.session import get_db
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter()


def service() -> QuestionService:
    settings = get_settings()
    return QuestionService(LocalFilesystemContentStore(), AIGateway(DeepSeekProvider(settings), settings))


@router.get("/search/questions")
def search_questions(q: str = Query(default=""), subject: str = "", question_type: str = "", method: str = "", status: str = "", limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return service().list(db, q=q, subject=subject, question_type=question_type, method=method, status=status, limit=limit, offset=offset)
