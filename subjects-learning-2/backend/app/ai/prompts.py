"""Backward-compatible prompt exports backed by the versioned prompt registry."""

from app.ai.prompt_registry import (
    POLICY_VERSION,
    REGISTRY_VERSION,
    PromptBundle,
    PromptRegistry,
    get_prompt_registry,
)

_registry = get_prompt_registry()
BASE_POLICY = _registry.policy

# Gateway still imports these names. Keep them stable while sourcing their content
# from the policy -> subject -> task composition used by PromptRegistry.
PREFLIGHT_PROMPT = _registry.get("preflight").system
PARSE_PROMPT = _registry.get("solve").system
REVIEW_PROMPT = _registry.get("review").system
CHAT_PROMPT = _registry.get("chat").system
KNOWLEDGE_IMPORT_PROMPT = _registry.get("knowledge_import").system

__all__ = [
    "BASE_POLICY",
    "CHAT_PROMPT",
    "KNOWLEDGE_IMPORT_PROMPT",
    "PARSE_PROMPT",
    "POLICY_VERSION",
    "PREFLIGHT_PROMPT",
    "REGISTRY_VERSION",
    "REVIEW_PROMPT",
    "PromptBundle",
    "PromptRegistry",
    "get_prompt_registry",
]
