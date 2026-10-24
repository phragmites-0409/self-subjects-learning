from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.errors import AppError

# Deliberately narrow repair: it only removes commas immediately before a closing
# object/array token outside JSON strings. It does not invent keys, values, quotes,
# or answer fields.
_TRAILING_COMMA_RE = re.compile(r",(?P<whitespace>\s*)(?P<closing>[}\]])")
_THINK_BLOCK_RE = re.compile(r"<think(?:ing)?\b[^>]*>.*?</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
_FENCED_JSON_RE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)


def structured_prompt(system: str, schema: type[BaseModel]) -> str:
    """Keep the requested fields and types tied to the actual validation model."""
    return (
        system
        + '\n只返回一个完整的 JSON 对象，不输出 Markdown、前后说明或内部思考。'
        '字段名称、类型、嵌套结构及必填项必须符合以下 JSON Schema；没有的信息按任务要求标注待核对，不虚构。'
        '字符串中的换行、双引号及反斜杠必须按 JSON 转义，尤其是 LaTeX。'
        '\nJSON 字符串格式示例：'
        + json.dumps('公式 $\\frac{1}{2}$\n下一行', ensure_ascii=False)
        + '\nJSON Schema：\n'
        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )


def _normalise_wrappers(text: str) -> str:
    candidate = text.strip()
    candidate = _THINK_BLOCK_RE.sub("", candidate).strip()
    if candidate.startswith("```"):
        candidate = _FENCED_JSON_RE.sub("", candidate, count=1)
        candidate = re.sub(r"\s*```\s*$", "", candidate)
    return candidate.strip()


def _parse_object(candidate: str) -> dict[str, Any]:
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise TypeError("JSON 根节点不是对象")
    return value


def _first_balanced_object(text: str) -> str | None:
    """Return the first balanced JSON object, respecting quoted braces."""

    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    # Do not skip an unmatched outer brace and accidentally accept a nested
    # object as the model's answer.
    return None


def _repair_trailing_commas(candidate: str) -> str:
    """Remove trailing commas outside strings in one bounded repair pass."""

    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(candidate):
        character = candidate[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue

        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == ",":
            closing_match = _TRAILING_COMMA_RE.match(candidate, index)
            if closing_match:
                output.extend(candidate[index + 1 : closing_match.start("closing")])
                index = closing_match.end("closing") - 1
                output.append(candidate[index])
                index += 1
                continue
        output.append(character)
        index += 1
    return "".join(output)


def extract_json(text: str) -> dict[str, Any]:
    """Extract an object from a model response with bounded, safe cleanup.

    Accepted wrappers are an optional ``<think>`` block, a JSON code fence, or
    short prose surrounding one object. Exactly one trailing-comma repair pass
    may be applied to the selected object. No missing content is fabricated.
    """

    if not isinstance(text, str) or not text.strip():
        raise AppError("AI_INVALID_JSON", "AI 返回内容不是有效 JSON", 502)

    candidate = _normalise_wrappers(text)

    # A complete JSON value is authoritative: arrays and scalar roots must not
    # be turned into an object merely because they contain braces somewhere.
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        value = None
    else:
        if not isinstance(value, dict):
            raise AppError("AI_INVALID_JSON", "AI 返回结构不正确", 502)
        return value

    if candidate.lstrip().startswith("["):
        raise AppError("AI_INVALID_JSON", "AI 返回结构不正确", 502)

    # Parse first, then perform at most one safe repair on the selected object.
    object_candidate = _first_balanced_object(candidate)
    if object_candidate is None:
        raise AppError("AI_INVALID_JSON", "AI 返回内容无法解析", 502)
    try:
        return _parse_object(object_candidate)
    except (json.JSONDecodeError, TypeError):
        repaired = _repair_trailing_commas(object_candidate)
        if repaired != object_candidate:
            try:
                return _parse_object(repaired)
            except (json.JSONDecodeError, TypeError):
                pass

    raise AppError("AI_INVALID_JSON", "AI 返回内容无法解析", 502)


def validate_output[ModelT: BaseModel](text: str, schema: type[ModelT]) -> ModelT:
    try:
        return schema.model_validate(extract_json(text))
    except ValidationError as exc:
        raise AppError(
            "AI_SCHEMA_INVALID",
            "AI 返回字段不符合预期",
            502,
            {"errors": exc.errors(include_url=False, include_context=False)},
        ) from exc
