from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.config import get_settings
from app.db.session import get_db
from app.modules.conversations.schemas import MessageRequest
from app.modules.conversations.service import ConversationService
from app.modules.devices.schemas import PairRequest
from app.modules.devices.service import DeviceService
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter()


def services():
    settings = get_settings()
    store = LocalFilesystemContentStore()
    questions = QuestionService(store, AIGateway(DeepSeekProvider(settings), settings))
    return questions, ConversationService(store, questions.gateway, questions)


def authenticated_device(x_device_key: str | None, scope: str, db: Session):
    return DeviceService().authenticate(db, x_device_key or "", scope)


@router.post("/pair")
def pair(request: PairRequest, db: Session = Depends(get_db)):
    return DeviceService().pair(db, request.name)


@router.get("/health")
def device_health(x_device_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    device = authenticated_device(x_device_key, "question:read", db)
    return {"ok": True, "device_id": device.id, "server": "ready"}


@router.get("/questions")
def device_questions(q: str = "", limit: int = Query(default=20, ge=1, le=50), x_device_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    authenticated_device(x_device_key, "question:read", db)
    return services()[0].list(db, q=q, limit=limit)


@router.get("/questions/{question_id}")
def device_question(question_id: str, x_device_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    authenticated_device(x_device_key, "question:read", db)
    return services()[0].detail(db, question_id)


@router.post("/questions/{question_id}/messages")
async def device_message(question_id: str, request: MessageRequest, x_device_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    authenticated_device(x_device_key, "chat:write", db)
    return await services()[1].send(db, question_id, request.text, request.conversation_id, request.client_request_id)
