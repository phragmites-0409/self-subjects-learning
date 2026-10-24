"""Derived images: originals are immutable; coordinates use the oriented page."""

import math
import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Asset
from app.storage.local_store import LocalFilesystemContentStore


def bounds(box: list[float], width: int, height: int):
    if len(box) != 4 or any(
        isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not math.isfinite(v)
        or not 0 <= v <= 1
        for v in box
    ):
        raise AppError("INVALID_BOX", "裁切坐标须为0至1之间的四个数", 422)
    left, top, right, bottom = box
    result = (
        int(left * width),
        int(top * height),
        math.ceil(right * width),
        math.ceil(bottom * height),
    )
    if result[2] - result[0] < 2 or result[3] - result[1] < 2:
        raise AppError("INVALID_BOX", "裁切区域过小或坐标顺序错误", 422)
    return result


def load_image(db: Session, aid: str) -> Image.Image:
    asset = db.get(Asset, aid)
    if not asset or asset.deleted_at or not asset.mime_type.startswith("image/"):
        raise AppError("ASSET_NOT_FOUND", "图像不存在", 404)
    with Image.open(
        BytesIO(LocalFilesystemContentStore().read_bytes(asset.storage_key))
    ) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def store_asset(
    db: Session, data: bytes, mime: str, kind: str, width=None, height=None
) -> Asset:
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }[mime]
    key, digest = LocalFilesystemContentStore().put_bytes(
        "answer-originals" if kind == "answer_source" else "derived-images",
        data,
        suffix,
    )
    asset = db.scalar(select(Asset).where(Asset.storage_key == key))
    if not asset:
        asset = Asset(
            kind=kind,
            storage_key=key,
            sha256=digest,
            mime_type=mime,
            byte_size=len(data),
            width=width,
            height=height,
        )
        db.add(asset)
        db.flush()
    return asset


def store_image(db: Session, im: Image.Image, kind="processed") -> str:
    buffer = BytesIO()
    im.save(buffer, "PNG")
    return store_asset(db, buffer.getvalue(), "image/png", kind, *im.size).id


def crop_image(db: Session, aid: str, box: list[float]) -> str:
    im = load_image(db, aid)
    return store_image(db, im.crop(bounds(box, *im.size)), "answer_crop")


def combine(db: Session, aids: list[str]) -> str:
    images = [load_image(db, aid) for aid in aids]
    width = max(im.width for im in images)
    height = sum(im.height for im in images) + 16 * (len(images) - 1)
    if width * height > 40_000_000:
        raise AppError("IMAGE_TOO_LARGE", "图像组合过大，请减少裁片", 422)
    result = Image.new("RGB", (width, height), "white")
    top = 0
    for im in images:
        result.paste(im, (0, top))
        top += im.height + 16
    return store_image(db, result)


def process_question(db: Session, aid: str, recognition) -> dict:
    image = load_image(db, aid)
    clean = image.copy()
    draw = ImageDraw.Draw(clean)
    diagram_bounds = [bounds(r.box, *clean.size) for r in recognition.diagram_regions]
    # Bare option labels mean the choices themselves are pictures. Approximate
    # model boxes cannot prove which curve belongs to which printed label.
    image_options = bool(recognition.has_diagram and recognition.options) and all(
        re.fullmatch(r"\s*[\[（(]?[A-H][\]）).、]?\s*", option)
        for option in recognition.options
    )
    removed = []
    protected = []
    # Only areas explicitly identified as isolated handwriting are erased.
    # Overlap with printed conditions is reported by OCR, never reconstructed.
    for region in recognition.handwriting_regions:
        left, top, right, bottom = bounds(region.box, *clean.size)
        if any(left < r and right > l and top < b and bottom > t for l, t, r, b in diagram_bounds):
            protected.append(region.box)
            continue
        draw.rectangle((left, top, right - 1, bottom - 1), fill="white")
        removed.append(region.box)
    clean = ImageOps.autocontrast(clean, cutoff=0.3, preserve_tone=True)
    clean = clean.filter(ImageFilter.UnsharpMask(radius=1, percent=110, threshold=3))
    processed_id = store_image(db, clean)
    diagrams = []
    for region in recognition.diagram_regions:
        diagrams.append(
            store_image(db, clean.crop(bounds(region.box, *clean.size)), "diagram")
        )
    result = {
        "processed_asset_id": processed_id,
        "diagram_asset_ids": diagrams,
        "removed_note_regions": removed,
        "protected_note_regions": protected,
        "image_processing_concerns": ["部分笔迹区域与示意图重叠，已保留，避免误擦图形与标注"] if protected else [],
        "diagram_crop_fallback": image_options,
    }
    if image_options:
        result["crop_asset_id"] = processed_id
        result["image_processing_concerns"].append(
            "选项内容为图形，已保留完整原题图用于打印，确保选项编号与图形匹配；可手动校对后调整裁图"
        )
    elif diagrams:
        result["crop_asset_id"] = (
            diagrams[0] if len(diagrams) == 1 else combine(db, diagrams)
        )
    return result
