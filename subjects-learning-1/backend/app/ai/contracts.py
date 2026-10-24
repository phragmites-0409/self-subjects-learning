from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMRequest:
    task: str
    system_prompt: str
    user_text: str
    image_bytes: bytes | None = None
    image_media_type: str = "image/webp"
    max_tokens: int = 8192
    temperature: float = 0.2
    additional_image_bytes: list[bytes] = field(default_factory=list)
    thinking: bool = False


@dataclass
class LLMResponse:
    text: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None


class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse: ...


class AIGatewayProtocol(Protocol):
    async def preflight(self, text: str, image_bytes: bytes | None = None) -> Any: ...
    async def parse_question(self, text: str, image_bytes: bytes | None = None) -> Any: ...
    async def review_question(self, content: Any) -> Any: ...
    async def chat(self, content: Any, history: list[dict[str, str]], question: str) -> Any: ...
