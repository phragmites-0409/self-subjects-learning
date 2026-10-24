from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.config import get_settings
from app.db.session import get_db
from app.modules.conversations.schemas import MessageRequest
from app.modules.conversations.service import ConversationService
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter()


def service() -> ConversationService:
    settings = get_settings()
    store = LocalFilesystemContentStore()
    questions = QuestionService(store, AIGateway(DeepSeekProvider(settings), settings))
    return ConversationService(store, questions.gateway, questions)


@router.get("/questions/{question_id}/conversations")
def list_conversations(question_id: str, db: Session = Depends(get_db)):
    return {"items": service().list(db, question_id)}


@router.post("/questions/{question_id}/messages")
async def send_message(question_id: str, request: MessageRequest, db: Session = Depends(get_db)):
    result = await service().send(db, question_id, request.text, request.conversation_id, request.client_request_id)
    return result
