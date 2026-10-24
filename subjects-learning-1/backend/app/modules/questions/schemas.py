from pydantic import BaseModel, Field


class QuestionUpdate(BaseModel):
    subject: str | None = None
    grade: str | None = None
    question_type: str | None = None
    difficulty: str | None = None
    methods: list[str] | None = None
    knowledge_points: list[str] | None = None
    tags: list[str] | None = None
    content: dict | None = None


class ParseRequest(BaseModel):
    text: str = Field(default="", max_length=10000)
