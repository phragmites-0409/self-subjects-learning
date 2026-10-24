from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

ENGLISH_KNOWLEDGE_KINDS = (
    "composition_category",
    "phrase",
    "sentence_pattern",
    "viewpoint",
    "material",
    "sample_excerpt",
)
EnglishKnowledgeKind = Literal[
    "composition_category",
    "phrase",
    "sentence_pattern",
    "viewpoint",
    "material",
    "sample_excerpt",
]


class SolutionStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = Field(ge=1)
    title: str = ""
    content: str = ""
    rationale: str = ""


class KnowledgeSuggestion(BaseModel):
    """A candidate knowledge node extracted from a question or source text."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    subject: str = ""
    chapter: str = ""
    description: str = ""
    reason: str = ""
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)


class KnowledgeRelationSuggestion(BaseModel):
    """A proposed relation between two knowledge-node identifiers."""

    model_config = ConfigDict(extra="ignore")

    source: str = ""
    target: str = ""
    relation: str = ""
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)


class KnowledgeMappingResult(BaseModel):
    """The intentionally small, reviewable knowledge-mapping output contract."""

    model_config = ConfigDict(extra="ignore")

    nodes: list[KnowledgeSuggestion] = Field(default_factory=list)
    edges: list[KnowledgeRelationSuggestion] = Field(default_factory=list)


class EnglishCompositionSuggestion(BaseModel):
    """A reviewable proposal for material that may enter English composition knowledge."""

    model_config = ConfigDict(extra="ignore")

    kind: EnglishKnowledgeKind
    content: str = Field(min_length=1)
    chinese_note: str = Field(
        default="",
        validation_alias=AliasChoices("chinese_note", "description", "note"),
    )
    applicable_themes: list[str] = Field(default_factory=list)
    source: str = "question"
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class EnglishCompositionResult(BaseModel):
    """Composition-only suggestions; persistence requires an explicit user action."""

    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["english-composition-v1"] = "english-composition-v1"
    suggestions: list[EnglishCompositionSuggestion] = Field(default_factory=list)


class VocabularyWordCandidate(BaseModel):
    """One word identified in source text, without a persistence instruction."""

    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1)
    context: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)


class VocabularyExtractResult(BaseModel):
    """Words extracted from input; it deliberately has no knowledge-node fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["vocabulary-extract-v1"] = "vocabulary-extract-v1"
    words: list[VocabularyWordCandidate] = Field(default_factory=list)


class VocabularySense(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_of_speech: str = Field(
        default="",
        validation_alias=AliasChoices("part_of_speech", "pos"),
    )
    meaning: str = Field(
        default="",
        validation_alias=AliasChoices("meaning", "definition", "chinese_meaning"),
    )
    normalized_meaning: str = ""
    order: int = Field(default=1, ge=1)
    context_meaning: bool = False


class VocabularyLookupResult(BaseModel):
    """Lookup display data only; callers decide whether and what to save."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["vocabulary-lookup-v1"] = "vocabulary-lookup-v1"
    word: str = ""
    lemma: str = ""
    senses: list[VocabularySense] = Field(default_factory=list)
    context_meaning: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)


# Short aliases keep the contract discoverable to callers that use the task name.
CompositionSuggestion = EnglishCompositionSuggestion
CompositionResult = EnglishCompositionResult
VocabularyWord = VocabularyWordCandidate


class QuestionContentV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["question-content-v1"] = "question-content-v1"
    subject: str = "高中综合"
    grade: str = "高中"
    chapter: str = ""
    question_type: str = "待分类"
    stem: str = ""
    options: list[str] = Field(default_factory=list)
    answer: str = ""
    overview: str = ""
    known_conditions: list[str] = Field(default_factory=list)
    target: str = ""
    methods: list[str] = Field(default_factory=list)
    model_path: list[str] = Field(default_factory=list)
    knowledge_points: list[str] = Field(default_factory=list)
    knowledge_candidates: list[str] = Field(default_factory=list)
    difficulty: str = "未知"
    solution_steps: list[SolutionStep] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    similar_question_ideas: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    source_text: str = ""


class PreflightResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["preflight-v1"] = "preflight-v1"
    decision: Literal[
        "ready",
        "needs_more_info",
        "not_high_school",
        "not_supported",
        "uncertain",
    ] = "uncertain"
    is_high_school: bool = True
    missing_information: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recognized_text: str = ""
    suggestion: str = ""


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["review-v1"] = "review-v1"
    status: Literal["pass", "fail", "uncertain"] = "uncertain"
    issues: list[str] = Field(default_factory=list)
    corrected_fields: list[str] = Field(default_factory=list)
    summary: str = ""


class ChatAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    related_step: int | None = None
    uncertainty_notes: list[str] = Field(default_factory=list)


class PromptOptimization(BaseModel):
    optimized_instruction: str
    rationale: str = ""
    cautions: list[str] = Field(default_factory=list)
