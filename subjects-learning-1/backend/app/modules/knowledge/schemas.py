from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_SUBJECTS = ("数学", "物理", "化学", "生物", "语文", "英语")
ENGLISH_KNOWLEDGE_KINDS = (
    "composition_category",
    "phrase",
    "sentence_pattern",
    "viewpoint",
    "material",
    "sample_excerpt",
)


def _validate_subject(value: str) -> str:
    if value not in SUPPORTED_SUBJECTS:
        raise ValueError(f"subject must be one of: {', '.join(SUPPORTED_SUBJECTS)}")
    return value


def _validate_subject_kind(subject: str, kind: str) -> tuple[str, str]:
    _validate_subject(subject)
    if subject == "英语" and kind not in ENGLISH_KNOWLEDGE_KINDS:
        allowed = ", ".join(ENGLISH_KNOWLEDGE_KINDS)
        raise ValueError(f"English knowledge nodes must use one of: {allowed}")
    return subject, kind


class KnowledgeNodeCreate(BaseModel):
    subject: str
    parent_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=32)
    summary: str = ""
    sort_order: int = 0
    status: str = "active"

    _subject_is_supported = field_validator("subject")(_validate_subject)

    @model_validator(mode="after")
    def english_nodes_are_composition_material(self) -> KnowledgeNodeCreate:
        _validate_subject_kind(self.subject, self.kind)
        return self


class KnowledgeNodeUpdate(BaseModel):
    subject: str | None = None
    parent_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, min_length=1, max_length=32)
    summary: str | None = None
    sort_order: int | None = None
    status: str | None = None

    _subject_is_supported = field_validator("subject")(_validate_subject)

    @model_validator(mode="after")
    def english_nodes_are_composition_material(self) -> KnowledgeNodeUpdate:
        # A patch with only one of subject/kind cannot prove the merged state.
        # Require both values when either is supplied; callers can then use
        # ``merged_subject_kind`` against the persisted node before applying it.
        if (self.subject is None) != (self.kind is None):
            raise ValueError("subject and kind must be supplied together for a knowledge-node update")
        if self.subject is not None and self.kind is not None:
            _validate_subject_kind(self.subject, self.kind)
        return self

    def merged_subject_kind(self, *, current_subject: str, current_kind: str) -> tuple[str, str]:
        """Return and validate the final subject/kind after applying this patch."""
        subject = self.subject if self.subject is not None else current_subject
        kind = self.kind if self.kind is not None else current_kind
        return _validate_subject_kind(subject, kind)


class KnowledgeNodeRead(KnowledgeNodeCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class KnowledgeEdgeCreate(BaseModel):
    source_id: str
    target_id: str
    relation: str = Field(min_length=1, max_length=32)


class KnowledgeEdgeRead(KnowledgeEdgeCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class KnowledgeContentCreate(BaseModel):
    node_id: str
    title: str = Field(min_length=1, max_length=200)
    content_storage_key: str = Field(min_length=1, max_length=512)
    source: str = Field(default="manual", min_length=1, max_length=32)
    content_hash: str = Field(min_length=1, max_length=64)


class KnowledgeContentRead(KnowledgeContentCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class QuestionKnowledgeCreate(BaseModel):
    question_id: str
    node_id: str
    relation: str = Field(default="tests", min_length=1, max_length=32)
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: str = Field(default="manual", min_length=1, max_length=32)


class QuestionKnowledgeRead(QuestionKnowledgeCreate):
    model_config = ConfigDict(from_attributes=True)


class KnowledgeNodeList(BaseModel):
    items: list[KnowledgeNodeRead] = Field(default_factory=list)
