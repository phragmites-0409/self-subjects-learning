"""Supabase Auth boundary and short-lived, server-held browser sessions."""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

import httpx
from app.core.config import get_settings
from app.core.errors import AppError
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "sl_session"


@dataclass
class BrowserSession:
    user_id: str
    email: str
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
        if response.status_code in (400, 401, 422):
            raise AppError("AUTH_REJECTED", "邮箱或密码无效，或账号尚未完成邮箱验证", 401)
        if response.status_code == 429:
            raise AppError("AUTH_RATE_LIMIT", "尝试过于频繁，请稍后再试", 429)
        raise AppError("AUTH_UNAVAILABLE", "登录服务暂时不可用", 503)
    return response.json() if response.content else {}


def _store_session(data: dict, response: JSONResponse) -> dict:
    user = data.get("user") or {}
    if not data.get("access_token") or not user.get("id"):
        raise AppError("EMAIL_CONFIRMATION_REQUIRED", "请先打开验证邮件，确认邮箱后再登录", 202)
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = BrowserSession(
        user_id=user["id"],
        email=user.get("email") or "",
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
    return {"id": user["id"], "email": user.get("email") or ""}


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
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    if not email or "@" not in email or len(email) > 254 or not password:
        raise AppError("INVALID_CREDENTIALS", "请填写有效邮箱和密码", 422)
    return email, password


@router.get("/config")
def config():
    return {"enabled": get_settings().auth_enabled}


@router.post("/register")
async def register(body: dict):
    email, password = _credentials(body)
    data = await _auth_request("POST", "signup", payload={"email": email, "password": password})
    return {"email_confirmation_required": not bool(data.get("access_token"))}


@router.post("/login")
async def login(body: dict):
    email, password = _credentials(body)
    data = await _auth_request(
        "POST", "token?grant_type=password", payload={"email": email, "password": password}
    )
    response = JSONResponse({"user": {"id": data["user"]["id"], "email": data["user"].get("email")}})
    _store_session(data, response)
    return response


@router.get("/me")
async def me(request: Request):
    session = await current_session(request)
    return {"id": session.user_id, "email": session.email}


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
