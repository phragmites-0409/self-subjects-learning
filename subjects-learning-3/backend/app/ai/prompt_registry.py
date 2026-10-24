from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

POLICY_VERSION = "high-school-gateway-v1"
REGISTRY_VERSION = "prompt-registry-v1"

SUPPORTED_SUBJECTS = ("数学", "物理", "化学", "生物", "语文", "英语")
SUPPORTED_TASKS = (
    "preflight",
    "solve",
    "review",
    "chat",
    "knowledge_import",
    "english_composition",
    "vocabulary_extract",
    "vocabulary_lookup",
)

_SUBJECT_FILES = {
    "数学": "math.zh.md",
    "物理": "physics.zh.md",
    "化学": "chemistry.zh.md",
    "生物": "biology.zh.md",
    "语文": "chinese.zh.md",
    "英语": "english_question.zh.md",
}
_TASK_FILES = {task: f"{task}.zh.md" for task in SUPPORTED_TASKS}
_TASK_ALIASES = {
    "parse_question": "solve",
    "parse": "solve",
    "review_question": "review",
}
_VOCABULARY_TASKS = frozenset({"vocabulary_extract", "vocabulary_lookup"})
_SUBJECT_ALIASES = {
    "数学": "数学",
    "物理": "物理",
    "化学": "化学",
    "生物": "生物",
    "语文": "语文",
    "英语": "英语",
    "英文": "英语",
    "英语单词": "英语",
}


@dataclass(frozen=True, slots=True)
class PromptBundle:
    version: str
    system: str


class PromptRegistry:
    """Load and compose the allow-listed Chinese prompt resources.

    The registry never interpolates caller text into a system prompt. Subject and
    task values are resolved through fixed maps, so user-controlled strings cannot
    select arbitrary files or become system instructions.
    """

    def __init__(self, prompt_dir: str | Path | None = None) -> None:
        self.prompt_dir = Path(prompt_dir) if prompt_dir is not None else Path(__file__).parent / "prompts"

    @cached_property
    def policy(self) -> str:
        return self._read("policy.zh.md")

    def get(self, task: str, subject: str | None = None) -> PromptBundle:
        task_key = self._normalise_task(task)
        subject_key = self._normalise_subject(subject)
        # Vocabulary is an isolated English-only contract. Refuse accidental
        # composition with another subject rather than silently widening scope.
        if task_key in _VOCABULARY_TASKS and subject_key != "英语":
            raise ValueError("词汇任务只支持英语科目")
        if task_key == "english_composition" and subject_key != "英语":
            raise ValueError("英语作文素材任务只支持英语科目")
        subject_text = self._subject_text(subject_key, subject, task_key=task_key)
        task_text = self._read(f"tasks/{_TASK_FILES[task_key]}")
        system = f"{self.policy.rstrip()}\n\n{subject_text.rstrip()}\n\n{task_text.rstrip()}\n"
        return PromptBundle(
            # Keep the public version stable for audit records; the selected
            # task/subject remains visible in the composed system text.
            version=POLICY_VERSION,
            system=system,
        )

    def _normalise_task(self, task: str) -> str:
        if not isinstance(task, str):
            raise TypeError("task 必须是字符串")
        task_key = _TASK_ALIASES.get(task.strip(), task.strip())
        if task_key not in _TASK_FILES:
            raise ValueError(f"不支持的 AI 任务: {task}")
        return task_key

    def _normalise_subject(self, subject: str | None) -> str | None:
        if subject is None or not subject.strip():
            return None
        return _SUBJECT_ALIASES.get(subject.strip())

    def _subject_text(
        self, subject_key: str | None, requested_subject: str | None, *, task_key: str
    ) -> str:
        if subject_key is None:
            if requested_subject and requested_subject.strip():
                return (
                    "【科目白名单回退】\n"
                    "输入标注的科目不在支持范围内；仅支持高中六科。"
                    "不得把未识别科目当作已确认科目，必须在输出中标记 uncertain 或 not_supported。"
                )
            return (
                "【通用科目回退】\n"
                "尚未确认具体科目。仅支持高中六科；不要猜测科目，先保留不确定性并请求确认。"
            )
        if subject_key == "英语" and task_key in _VOCABULARY_TASKS:
            return self._read("subjects/english_words.zh.md")
        return self._read(f"subjects/{_SUBJECT_FILES[subject_key]}")

    def _read(self, relative_path: str) -> str:
        path = self.prompt_dir / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"提示词资源不可用: {relative_path}") from exc
        if not text.strip():
            raise RuntimeError(f"提示词资源为空: {relative_path}")
        return text


@lru_cache(maxsize=1)
def get_prompt_registry() -> PromptRegistry:
    """Return the process-wide cached prompt registry."""

    return PromptRegistry()
