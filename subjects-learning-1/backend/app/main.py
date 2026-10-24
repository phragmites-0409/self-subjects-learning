import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as api_router
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_data_dirs()
    init_db()
    from app.db.session import SessionLocal
    from app.modules.learning.service import plan

    if settings.app_env != "test":
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

    async def maintain():
        while True:
            try:
                with SessionLocal() as db:
                    plan(db)
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

objects_dir = settings.data_dir / "objects"
app.mount("/media", StaticFiles(directory=str(objects_dir)), name="media")


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "application_id": "subjects-learning",
        "version": "-1",
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
