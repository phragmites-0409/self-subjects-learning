import json
from typing import Any

from app.ai.contracts import LLMProvider, LLMRequest
from app.ai.prompts import (
    CHAT_PROMPT,
    PARSE_PROMPT,
    PREFLIGHT_PROMPT,
    REVIEW_PROMPT,
)
from app.ai.schemas import ChatAnswer, PreflightResult, QuestionContentV1, ReviewResult
from app.ai.validator import structured_prompt, validate_output
from app.core.config import Settings


class AIGateway:
    def __init__(self, provider: LLMProvider, settings: Settings):
        self.provider = provider
        self.settings = settings

    async def _generate_json(self, task: str, system: str, user_text: str, image_bytes: bytes | None, schema: type[Any], demo: dict[str, Any]) -> Any:
        thinking = task in {"parse_question", "review_question", "chat"}
        request = LLMRequest(
            task=task, system_prompt=structured_prompt(system, schema), user_text=user_text,
            image_bytes=image_bytes, thinking=thinking, max_tokens=32768 if thinking else 8192,
        )
        response = await self.provider.generate(request)
        if not response.text:
            from app.core.errors import AppError
            if response.usage.get("demo"):
                raise AppError("AI_NOT_CONFIGURED", "尚未配置AI，不能生成真实识别、解析或对话结果", 409)
            raise AppError("AI_EMPTY_RESPONSE", "AI 未返回回答内容，请重试", 502)
        return validate_output(response.text, schema)

    async def preflight(self, text: str, image_bytes: bytes | None = None) -> PreflightResult:
        demo = {"decision": "ready", "is_high_school": True, "recognized_text": text or "待由视觉模型识别", "concerns": [], "missing_information": [], "suggestion": "演示模式：请确认题目内容完整。"}
        return await self._generate_json("preflight", PREFLIGHT_PROMPT, text or "请检查图片中的题目。", image_bytes, PreflightResult, demo)

    async def parse_question(self, text: str, image_bytes: bytes | None = None) -> QuestionContentV1:
        demo = {
            "subject": "数学", "grade": "高中", "chapter": "待确认", "question_type": "待确认",
            "stem": text or "演示题目：请配置 DeepSeek 后进行图片识别。", "source_text": text,
            "overview": "当前为演示解析，请配置 DeepSeek API 后获得真实题目分析。", "target": "根据题目条件求解未知量",
            "answer": "待 AI 分析", "methods": ["待 AI 判断"], "knowledge_points": ["待 AI 判断"],
            "difficulty": "未知", "confidence": 0.1,
            "known_conditions": ["题目内容来自用户上传的图片或文字"],
            "solution_steps": [{"index": 1, "title": "确认题目", "content": "请先确认识别出的题干、数字和图形条件。", "rationale": "避免在信息不完整时猜测。"}],
            "common_mistakes": ["未检查图片中的公式、单位和图形关系"], "uncertainty_notes": ["演示模式未调用外部 AI"], "similar_question_ideas": []
        }
        return await self._generate_json("parse_question", PARSE_PROMPT, text or "请识别并解析图片中的高中题目。", image_bytes, QuestionContentV1, demo)

    async def review_question(self, content: QuestionContentV1) -> ReviewResult:
        demo = {"status": "uncertain", "issues": ["演示模式未执行外部 AI 复核"], "corrected_fields": [], "summary": "请配置 DeepSeek 后执行复核。"}
        return await self._generate_json("review_question", REVIEW_PROMPT, json.dumps(content.model_dump(), ensure_ascii=False), None, ReviewResult, demo)

    async def chat(self, content: QuestionContentV1, history: list[dict[str, str]], question: str) -> ChatAnswer:
        context = {"question": content.model_dump(), "history": history[-8:], "user_question": question}
        demo = {"answer": "当前是演示模式。配置 DeepSeek API 后，我会结合这道高中题目的题干、步骤和上下文回答你的问题。", "key_points": [], "related_step": None, "uncertainty_notes": ["尚未调用外部 AI"]}
        return await self._generate_json("chat", CHAT_PROMPT, json.dumps(context, ensure_ascii=False), None, ChatAnswer, demo)
