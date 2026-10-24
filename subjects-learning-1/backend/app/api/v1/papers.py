from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Paper
from app.db.session import get_db
from app.modules.papers.schemas import PaperCreate, PaperUpdate
from app.modules.papers.service import PaperService
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter()


def service() -> PaperService:
    settings = get_settings()
    store = LocalFilesystemContentStore()
    questions = QuestionService(store, AIGateway(DeepSeekProvider(settings), settings))
    return PaperService(store, settings, questions)


@router.get("")
def list_papers(db: Session = Depends(get_db)):
    return {"items": service().list(db)}


@router.post("")
def create_paper(request: PaperCreate, db: Session = Depends(get_db)):
    return service().create(db, request.title, request.subject, request.grade, [item.model_dump() for item in request.items])


@router.get("/{paper_id}")
def get_paper(paper_id: str, db: Session = Depends(get_db)):
    return service().get(db, paper_id)


@router.patch("/{paper_id}")
def update_paper(paper_id: str, request: PaperUpdate, db: Session = Depends(get_db)):
    paper = db.get(Paper, paper_id)
    if not paper:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
    return service().update(db, paper, request.model_dump(exclude_none=True))


@router.post("/{paper_id}/export")
def export_paper(paper_id: str, include_answers: bool = False, db: Session = Depends(get_db)):
    paper = db.get(Paper, paper_id)
    if not paper:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
    return service().export(db, paper, include_answers)
