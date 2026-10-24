"""Request-local account storage selection. The legacy -3 data stays unassigned."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from uuid import UUID

_account_id: ContextVar[str | None] = ContextVar("account_id", default=None)


def account_id() -> str | None:
    return _account_id.get()


def set_account(value: str):
    normalized = str(UUID(value))
    return _account_id.set(normalized)


def reset_account(token) -> None:
    _account_id.reset(token)


def active_data_dir() -> Path:
    from app.core.config import get_settings

    root = get_settings().data_dir
    owner = account_id()
    return root / "accounts" / owner if owner else root


def schedule(background, task: Callable[..., Awaitable], *args) -> None:
    """Capture the authenticated owner before a response releases request scope."""
    owner = account_id()

    async def run() -> None:
        scope = set_account(owner) if owner else None
        try:
            await task(*args)
        finally:
            if scope is not None:
                reset_account(scope)

    background.add_task(run)
