"""Supabase Auth boundary and short-lived, server-held browser sessions."""

import asyncio
import logging
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256

import httpx
from app.core.config import get_settings
from app.core.errors import AppError
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "sl_session"


@dataclass
class BrowserSession:
    user_id: str
    username: str
    access_token: str
    refresh_token: str
    access_expires_at: float
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_sessions: dict[str, BrowserSession] = {}


def _configured():
    settings = get_settings()
    if not settings.auth_enabled:
        raise AppError("AUTH_NOT_CONFIGURED", "登录服务尚未连接 Supabase", 503)
    return settings


async def _auth_request(method: str, path: str, *, payload=None, token: str = "") -> dict:
    settings = _configured()
    headers = {"apikey": settings.supabase_publishable_key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method,
                f"{settings.supabase_url.rstrip('/')}/auth/v1/{path}",
                json=payload,
                headers=headers,
            )
    except httpx.RequestError as exc:
        raise AppError("AUTH_UNAVAILABLE", "登录服务暂时无法连接", 503) from exc
    if response.is_error:
        error_code = (response.json().get("error_code") or "") if response.headers.get("content-type", "").startswith("application/json") else ""
        if path == "signup" and error_code in {"user_already_exists", "email_exists"}:
            raise AppError("USERNAME_TAKEN", "用户名已被占用", 409)
        if path == "signup" and error_code == "email_address_invalid":
            raise AppError("AUTH_SETUP_REQUIRED", "内部账号标识被 Supabase 拒绝，请检查认证配置", 503)
        if path == "signup" and response.status_code in (400, 422):
            raise AppError("REGISTRATION_REJECTED", "注册失败，请检查用户名和密码", 422)
        if response.status_code in (400, 401, 422):
            raise AppError("AUTH_REJECTED", "用户名或密码无效", 401)
        if response.status_code == 429:
            raise AppError("AUTH_RATE_LIMIT", "尝试过于频繁，请稍后再试", 429)
        raise AppError("AUTH_UNAVAILABLE", "登录服务暂时不可用", 503)
    return response.json() if response.content else {}


def _store_session(data: dict, response: JSONResponse, username: str) -> dict:
    user = data.get("user") or {}
    if not data.get("access_token") or not user.get("id"):
        raise AppError("AUTH_SETUP_REQUIRED", "该账号无法登录，请检查 Supabase 邮箱确认设置", 503)
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = BrowserSession(
        user_id=user["id"],
        username=username,
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        access_expires_at=time.time() + int(data.get("expires_in", 3600)),
    )
    response.set_cookie(
        COOKIE,
        session_id,
        httponly=True,
        secure=get_settings().app_env == "production",
        samesite="strict",
        max_age=7 * 86400,
        path="/",
    )
    return {"id": user["id"], "username": username}


async def current_session(request: Request) -> BrowserSession:
    session_id = request.cookies.get(COOKIE, "")
    session = _sessions.get(session_id)
    if not session:
        raise AppError("LOGIN_REQUIRED", "请先登录", 401)
    if session.access_expires_at <= time.time() + 60:
        async with session.refresh_lock:
            if session.access_expires_at <= time.time() + 60:
                try:
                    data = await _auth_request(
                        "POST",
                        "token?grant_type=refresh_token",
                        payload={"refresh_token": session.refresh_token},
                    )
                except AppError as exc:
                    if exc.status_code == 401:
                        _sessions.pop(session_id, None)
                        raise AppError("LOGIN_REQUIRED", "登录已失效，请重新登录", 401) from exc
                    raise
                if data.get("user", {}).get("id") != session.user_id:
                    _sessions.pop(session_id, None)
                    raise AppError("LOGIN_REQUIRED", "登录已失效，请重新登录", 401)
                session.access_token = data["access_token"]
                session.refresh_token = data["refresh_token"]
                session.access_expires_at = time.time() + int(data.get("expires_in", 3600))
    return session


def _credentials(body: dict) -> tuple[str, str]:
    username = unicodedata.normalize("NFKC", str(body.get("username", "")).strip()).lower()
    password = str(body.get("password", ""))
    if (not 3 <= len(username) <= 24 or not username[0].isalnum()
            or not all(char.isalnum() or char in "_-" for char in username)
            or not 8 <= len(password) <= 128):
        raise AppError("INVALID_CREDENTIALS", "用户名须为 3–24 个字母、数字、下划线或连字符；密码须为 8–128 位", 422)
    return username, password


def _auth_email(username: str) -> str:
    """Private, deterministic Supabase Auth identifier; never shown to users."""
    return f"{sha256(username.encode('utf-8')).hexdigest()}@accounts.subjects-learning.invalid"


@router.get("/config")
def config():
    return {"enabled": get_settings().auth_enabled}


@router.post("/register")
async def register(body: dict):
    username, password = _credentials(body)
    settings = await _auth_request("GET", "settings")
    if settings.get("mailer_autoconfirm") is not True:
        raise AppError("AUTH_SETUP_REQUIRED", "请先在 Supabase 关闭 Confirm email，才能使用无邮箱注册", 503)
    data = await _auth_request("POST", "signup", payload={
        "email": _auth_email(username), "password": password,
        "data": {"username": username},
    })
    if not data.get("access_token"):
        raise AppError("AUTH_SETUP_REQUIRED", "注册未能自动确认，请检查 Supabase 的 Confirm email 设置", 503)
    return {"username": username}


async def _sync_directory_after_login(user_id: str, token: str) -> None:
    """Best-effort directory refresh; login must work even while cloud is unavailable."""
    from app.core.account_scope import reset_account, set_account
    from app.db.session import SessionLocal
    from app.modules.accounts.cloud_catalog import sync_catalog

    scope = set_account(user_id)
    try:
        with SessionLocal() as db:
            await sync_catalog(db, user_id, token)
    except Exception:
        logging.getLogger(__name__).exception("Cloud directory refresh after login failed")
    finally:
        reset_account(scope)


@router.post("/login")
async def login(body: dict, background: BackgroundTasks):
    username, password = _credentials(body)
    data = await _auth_request(
        "POST", "token?grant_type=password", payload={"email": _auth_email(username), "password": password}
    )
    if data.get("user", {}).get("user_metadata", {}).get("username") != username:
        raise AppError("AUTH_REJECTED", "用户名或密码无效", 401)
    response = JSONResponse({"user": {"id": data["user"]["id"], "username": username}})
    _store_session(data, response, username)
    background.add_task(_sync_directory_after_login, data["user"]["id"], data["access_token"])
    response.background = background
    return response


@router.get("/me")
async def me(request: Request):
    session = await current_session(request)
    return {"id": session.user_id, "username": session.username}


@router.post("/logout")
async def logout(request: Request):
    session_id = request.cookies.get(COOKIE, "")
    session = _sessions.pop(session_id, None)
    if session:
        try:
            await _auth_request("POST", "logout", token=session.access_token)
        except AppError:
            pass
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/")
    return response
