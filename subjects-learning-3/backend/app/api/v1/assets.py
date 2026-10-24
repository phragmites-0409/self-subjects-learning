from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Asset
from app.db.session import get_db
from app.documents.image_pipeline import ALLOWED_MIME, normalize_image
from app.modules.learning import service as flow
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter()


def question_service() -> QuestionService:
    settings = get_settings()
    return QuestionService(
        LocalFilesystemContentStore(), AIGateway(DeepSeekProvider(settings), settings)
    )


@router.post("/assets")
async def upload_asset(
    file: UploadFile = File(...),
    text: str = Form(""),
    purpose: str = Form("question"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if file.content_type not in ALLOWED_MIME:
        raise AppError("UNSUPPORTED_IMAGE", "仅支持 JPG、PNG 或 WebP 图片", 415)
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise AppError("FILE_TOO_LARGE", "图片不能超过 10 MB", 413)
    try:
        _normalized, preview, width, height = normalize_image(data)
    except Exception as exc:
        raise AppError("INVALID_IMAGE", "无法读取这张图片，请重新上传", 422) from exc
    with flow.LOCK:
        store = LocalFilesystemContentStore()
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[
            file.content_type
        ]
        source_key, source_hash = store.put_bytes("original-images", data, suffix)
        preview_key, preview_hash = store.put_bytes("thumbnails", preview, ".webp")
        source = db.query(Asset).filter(Asset.storage_key == source_key).first()
        if not source:
            from io import BytesIO

            from PIL import Image, ImageOps

            with Image.open(BytesIO(data)) as image:
                width, height = ImageOps.exif_transpose(image).size
            source = Asset(
                kind="image",
                storage_key=source_key,
                sha256=source_hash,
                mime_type=file.content_type,
                byte_size=len(data),
                width=width,
                height=height,
            )
            db.add(source)
            db.flush()
        source.deleted_at = None
        thumbnail = db.query(Asset).filter(Asset.storage_key == preview_key).first()
        if not thumbnail:
            thumbnail = Asset(
                kind="thumbnail",
                storage_key=preview_key,
                sha256=preview_hash,
                mime_type="image/webp",
                byte_size=len(preview),
                width=min(width, 640),
                height=min(height, 640),
            )
            db.add(thumbnail)
        thumbnail.deleted_at = None
        db.commit()
        question = (
            question_service().create_from_asset(db, source, text)
            if purpose == "question"
            else None
        )
        if question:
            state = flow.state_for(db, question.id)
            state.data = {**state.data, "source_thumbnail_asset_ids": [thumbnail.id]}
            db.commit()
        return {
            "asset_id": source.id,
            "thumbnail_asset_id": thumbnail.id,
            "question_id": question.id if question else None,
            "width": source.width,
            "height": source.height,
            "sha256": source.sha256,
        }


@router.get("/assets/{asset_id}/download")
def download_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if not asset or asset.deleted_at:
        raise AppError("ASSET_NOT_FOUND", "文件不存在", 404)
    store = LocalFilesystemContentStore()
    path = store.path_for(asset.storage_key)
    if not path.exists():
        raise AppError("ASSET_MISSING", "文件内容不存在", 500)
    return FileResponse(path, media_type=asset.mime_type, filename=path.name)
