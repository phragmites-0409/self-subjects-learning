from pydantic import BaseModel, Field


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    client_request_id: str | None = Field(default=None, max_length=128)
