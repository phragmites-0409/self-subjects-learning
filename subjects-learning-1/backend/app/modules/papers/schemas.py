from pydantic import BaseModel, Field


class PaperItemInput(BaseModel):
    question_id: str
    question_version_id: str | None = None
    points: float = Field(default=5, ge=0, le=100)
    section_name: str = "基础题"


class PaperCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subject: str = "高中综合"
    grade: str = "高中"
    items: list[PaperItemInput] = Field(default_factory=list)


class PaperUpdate(BaseModel):
    title: str | None = None
    subject: str | None = None
    grade: str | None = None
    items: list[PaperItemInput] | None = None
