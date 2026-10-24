from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.core.errors import AppError
from app.db.models import Conversation, Message, Question
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore


class ConversationService:
    def __init__(self, store: LocalFilesystemContentStore, gateway: AIGateway, questions: QuestionService):
        self.store = store
        self.gateway = gateway
        self.questions = questions

    def get_or_create(self, db: Session, question_id: str, conversation_id: str | None = None) -> Conversation:
        if conversation_id:
            conversation = db.get(Conversation, conversation_id)
            if conversation and conversation.question_id == question_id:
                return conversation
        conversation = Conversation(question_id=question_id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    def list(self, db: Session, question_id: str) -> list[dict]:
        conversations = db.scalars(select(Conversation).where(Conversation.question_id == question_id).order_by(Conversation.updated_at.desc())).all()
        return [self.serialize(conversation) for conversation in conversations]

    @staticmethod
    def serialize(conversation: Conversation) -> dict:
        return {"id": conversation.id, "question_id": conversation.question_id, "title": conversation.title, "summary": conversation.summary, "messages": [{"id": item.id, "role": item.role, "content": item.content, "created_at": item.created_at} for item in conversation.messages]}

    async def send(self, db: Session, question_id: str, text: str, conversation_id: str | None = None, client_request_id: str | None = None) -> dict:
        if not text.strip() or len(text) > 4000:
            raise AppError("INVALID_MESSAGE", "问题不能为空且不能超过 4000 字", 422)
        question = db.get(Question, question_id)
        if not question:
            raise AppError("QUESTION_NOT_FOUND", "题目不存在", 404)
        conversation = self.get_or_create(db, question_id, conversation_id)
        if client_request_id:
            existing = db.scalar(select(Message).where(Message.conversation_id == conversation.id, Message.client_request_id == client_request_id, Message.role == "assistant"))
            if existing:
                return {"conversation": self.serialize(conversation), "answer": existing.content, "message_id": existing.id, "deduplicated": True}
        user_message = Message(conversation_id=conversation.id, role="user", content=text, client_request_id=client_request_id)
        db.add(user_message)
        db.commit()
        detail = self.questions.detail(db, question_id)
        content = detail.get("content", {})
        history = [{"role": message.role, "content": message.content} for message in conversation.messages[-8:]]
        answer = await self.gateway.chat(content, history, text)
        assistant_message = Message(conversation_id=conversation.id, role="assistant", content=answer.answer)
        db.add(assistant_message)
        conversation.updated_at = conversation.updated_at
        db.commit()
        db.refresh(assistant_message)
        return {"conversation": self.serialize(conversation), "answer": answer.model_dump(), "message_id": assistant_message.id, "deduplicated": False}
