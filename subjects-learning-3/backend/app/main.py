import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as api_router
from app.core.account_scope import reset_account, set_account
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_data_dirs()
    init_db(include_legacy=not settings.auth_enabled)
    from app.db.session import SessionLocal
    from app.modules.learning.service import plan

    if settings.app_env != "test" and not settings.auth_enabled:
        from sqlalchemy import select

        from app.modules.learning.models import AnswerPage, QuestionState

        with SessionLocal() as db:
            for state in db.scalars(select(QuestionState)):
                if state.data.get("recognition") in ("queued", "running"):
                    state.data = {
                        **state.data,
                        "recognition": "failed",
                        "recognition_note": "上次识别被中断，原件已经保存，可点击重新识别",
                    }
            for page in db.scalars(select(AnswerPage)):
                if page.data.get("status") in ("queued", "running"):
                    page.data = {**page.data, "status": "failed", "note": "上次答案识别被中断，原页已保存，可重新识别"}
            db.commit()

    def maintenance_tick():
        from app.modules.learning.draft_cleanup import retry_pending_cleanup
        from app.modules.notifications import maintain as notify

        owners = [None]
        if settings.auth_enabled:
            owners = [folder.name for folder in (settings.data_dir / "accounts").glob("*") if folder.is_dir()]
        for owner in owners:
            try:
                scope = set_account(owner) if owner else None
            except ValueError:
                continue
            try:
                with SessionLocal() as db:
                    retry_pending_cleanup(db)
                    plan(db)
                    notify(db)
            finally:
                if scope is not None:
                    reset_account(scope)

    async def maintain():
        while True:
            try:
                await asyncio.to_thread(maintenance_tick)
            except Exception:
                import logging

                logging.getLogger(__name__).exception("Local daily maintenance failed")
            await asyncio.sleep(60)

    worker = asyncio.create_task(maintain()) if settings.app_env != "test" else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_exception_handler(AppError, app_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.middleware("http")
async def account_boundary(request: Request, call_next):
    if not settings.auth_enabled:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        allowed = {str(request.base_url).rstrip("/"), *settings.cors_origin_list}
        if origin and origin not in allowed:
            return JSONResponse({"error": {"code": "INVALID_ORIGIN", "message": "请求来源无效"}}, status_code=403)
    public = path in {
        "/api/v1/health", "/api/v1/auth/config", "/api/v1/auth/register", "/api/v1/auth/login"
    } or (not path.startswith("/api/") and not path.startswith("/media/"))
    if public:
        return await call_next(request)
    from app.modules.accounts.auth import current_session

    try:
        session = await current_session(request)
        scope = set_account(session.user_id)
    except (AppError, ValueError) as exc:
        return await app_error_handler(request, exc) if isinstance(exc, AppError) else JSONResponse(
            {"error": {"code": "INVALID_USER", "message": "用户身份无效"}}, status_code=401
        )
    try:
        return await call_next(request)
    finally:
        reset_account(scope)


@app.get("/media/{storage_key:path}")
def media(storage_key: str):
    from app.storage.local_store import LocalFilesystemContentStore

    try:
        path = LocalFilesystemContentStore().path_for(storage_key)
    except ValueError:
        raise HTTPException(status_code=404)
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "application_id": "subjects-learning",
        "version": "-3",
        "data_directory": str(settings.data_dir),
        "app": settings.app_name,
        "ai_configured": bool(settings.deepseek_api_key),
    }


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    assets_dist = frontend_dist / "assets"
    if assets_dist.exists():
        app.mount(
            "/assets", StaticFiles(directory=str(assets_dist)), name="frontend-assets"
        )

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def frontend_fallback(frontend_path: str):
        if frontend_path == "api" or frontend_path.startswith("api/"):
            raise HTTPException(status_code=404)
        requested_file = frontend_dist / frontend_path
        if (
            requested_file.is_file()
            and frontend_dist.resolve() in requested_file.resolve().parents
        ):
            return FileResponse(requested_file)
        return FileResponse(frontend_dist / "index.html")
