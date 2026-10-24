from pydantic import BaseModel, Field


class PairRequest(BaseModel):
    name: str = Field(default="AI 终端", max_length=100)
