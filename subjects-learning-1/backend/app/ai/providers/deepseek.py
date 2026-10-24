import base64
import logging
from typing import Any

import httpx

from app.ai.contracts import LLMRequest, LLMResponse
from app.core.config import Settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


def _unsupported_json_mode(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        error = response.json().get("error", {})
        message = str(error.get("message", "")).lower()
        return (
            (error.get("param") == "response_format" or "response_format" in message)
            and any(word in message for word in ("unsupported", "not supported", "unknown", "unrecognized"))
        )
    except (ValueError, AttributeError):
        return False


class DeepSeekProvider:
    """DeepSeek-compatible chat-completions adapter; the API key never leaves this process."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def model_for(self, request: LLMRequest) -> str:
        return self.settings.deepseek_vision_model if request.image_bytes or request.additional_image_bytes else self.settings.deepseek_model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.settings.deepseek_api_key:
            return LLMResponse(text="", model="demo", usage={"demo": True})

        model = self.model_for(request)
        user_content: Any = request.user_text
        if request.image_bytes or request.additional_image_bytes:
            user_content = [{"type": "text", "text": request.user_text}]
            for raw in ([request.image_bytes] if request.image_bytes else []) + request.additional_image_bytes:
                encoded = base64.b64encode(raw).decode("ascii")
                user_content.append({"type": "image_url", "image_url": {"url": f"data:{request.image_media_type};base64,{encoded}"}})
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if model.startswith("deepseek-"):
            payload["thinking"] = {"type": "enabled" if request.thinking else "disabled"}
            if request.thinking:
                payload["reasoning_effort"] = "low"
        headers = {"Authorization": f"Bearer {self.settings.deepseek_api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
                response = await client.post(f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
                if _unsupported_json_mode(response):
                    payload.pop("response_format")
                    response = await client.post(f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise AppError("AI_TIMEOUT", "AI 请求超时，请稍后重试", 504) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            code = "AI_RATE_LIMITED" if status == 429 else "AI_PROVIDER_ERROR"
            message = "AI 请求频率受限，请稍后重试" if status == 429 else f"AI 服务返回 HTTP {status}"
            raise AppError(code, message, 502, {"status": status}) from exc
        except httpx.HTTPError as exc:
            raise AppError("AI_NETWORK_ERROR", "无法连接 AI 服务", 502) from exc
        except ValueError as exc:
            raise AppError("AI_BAD_RESPONSE", "AI 服务返回格式异常", 502) from exc

        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError("AI_BAD_RESPONSE", "AI 服务缺少回答内容", 502) from exc
        if isinstance(text, list):
            text = "".join(part["text"] for part in text if isinstance(part, dict) and isinstance(part.get("text"), str))
        usage = data.get("usage") or {}
        details = {"model": model, "finish_reason": finish_reason, "max_tokens": request.max_tokens}
        # Keep diagnostics useful without logging API keys, images or model reasoning.
        logger.info("AI task=%s model=%s finish=%s content_chars=%s completion_tokens=%s",
                    request.task, model, finish_reason, len(text) if isinstance(text, str) else 0,
                    usage.get("completion_tokens"))
        if finish_reason == "length":
            raise AppError("AI_OUTPUT_TRUNCATED", "AI 输出额度已用完，回答未完成，请重试或缩小图片范围", 502, details)
        if finish_reason == "content_filter":
            raise AppError("AI_CONTENT_FILTERED", "AI 服务未提供可用回答，请检查输入内容", 502, details)
        if text is None or (isinstance(text, str) and not text.strip()):
            raise AppError("AI_EMPTY_RESPONSE", "AI 未返回回答内容，请重试", 502, details)
        if not isinstance(text, str):
            raise AppError("AI_BAD_RESPONSE", "AI 服务回答格式异常", 502, details)
        return LLMResponse(text=text, model=str(data.get("model", model)), usage=usage, request_id=response.headers.get("x-request-id"))
