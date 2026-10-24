from __future__ import annotations

from datetime import date

from app.modules.knowledge.schemas import SUPPORTED_SUBJECTS
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_subject(value: str) -> str:
    if value not in SUPPORTED_SUBJECTS:
        raise ValueError(f"subject must be one of: {', '.join(SUPPORTED_SUBJECTS)}")
    return value


class ErrorEntryCreate(BaseModel):
    question_id: str
    added_date: date
    subject: str
    question_type: str = Field(min_length=1, max_length=128)
    tags_json: list[str] = Field(default_factory=list)
    error_reason: str = ""
    status: str = "open"
    note: str = ""

    _subject_is_supported = field_validator("subject")(_validate_subject)


class ErrorEntryUpdate(BaseModel):
    added_date: date | None = None
    subject: str | None = None
    question_type: str | None = Field(default=None, min_length=1, max_length=128)
    tags_json: list[str] | None = None
    error_reason: str | None = None
    status: str | None = None
    note: str | None = None

    _subject_is_supported = field_validator("subject")(_validate_subject)


class ErrorEntryRead(ErrorEntryCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class ErrorReviewCreate(BaseModel):
    error_entry_id: str
    reviewed_date: date
    result: str = Field(min_length=1, max_length=32)
    note: str = ""


class ErrorReviewRead(ErrorReviewCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class ErrorEntryList(BaseModel):
    items: list[ErrorEntryRead] = Field(default_factory=list)
