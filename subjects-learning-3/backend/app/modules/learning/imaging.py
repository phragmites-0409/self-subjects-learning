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
    asset.deleted_at = None
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


def process_question(db: Session, aid: str, recognition, ink="off", pencil="balanced", exclusions=None) -> dict:
    image = load_image(db, aid)
    if exclusions:
        from app.modules.learning.note_filter import apply
        image=apply(image,exclusions)
    clean = image.copy()
    color_pixels = 0
    if ink != "off":
        from app.modules.learning.local_ocr import clean_color_notes

        clean, color_pixels = clean_color_notes(clean, ink)
    from app.modules.learning.diagram_processing import pencil_cleanup, diagram_sheet
    before_pencil = clean.copy()
    clean, pencil_info = pencil_cleanup(clean, pencil)
    diagram_bounds = [bounds(r.box, *clean.size) for r in [*recognition.diagram_regions,*recognition.inline_regions]]
    # Default processing must retain faint printed curves. Gray pencil over
    # those curves needs an explicit local mask, not whole-figure thresholding.
    protect_gray = bool(diagram_bounds and pencil in ("gentle", "balanced"))
    if protect_gray:
        for box in diagram_bounds:
            clean.paste(before_pencil.crop(box), box[:2])
    draw = ImageDraw.Draw(clean)
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
        if any(
            left < r and right > l and top < b and bottom > t
            for l, t, r, b in diagram_bounds
        ):
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
        **pencil_info,
        "crop_asset_id": None,
        "print_options_embedded": False,
        "diagram_layout": "single" if diagrams else "none",
        "image_confirmed_asset_id": None,
        "image_review_required": bool(recognition.has_diagram or diagrams or recognition.inline_regions),
        "processed_asset_id": processed_id,
        "diagram_asset_ids": diagrams,
        "removed_note_regions": removed,
        "protected_note_regions": protected,
        "image_processing_concerns": [
            "部分笔迹区域与示意图重叠，已保留，避免误擦图形与标注"
        ]
        if protected
        else [],
        "diagram_crop_fallback": image_options,
        "removed_color_pixels": color_pixels,
        "inline_images":[inline_asset(db,before_pencil,item) for item in recognition.inline_regions],
    }
    expected = [re.search(r"[A-H]", option).group(0) for option in recognition.options] if image_options else []
    if protect_gray:
        result["image_processing_concerns"].append("浅色题图线条已保护；图内铅笔残留请局部擦除并核对，强度减淡可能同时损伤浅色印刷线")
    paired = [r.label for r in recognition.diagram_regions if getattr(r, "label", "")]
    split_options = image_options and len(set(expected)) == len(expected) and sorted(paired) == sorted(expected)
    if split_options:
        parts = []
        for region in recognition.diagram_regions:
            box = list(region.box)
            if region.label and region.label_box:
                # Preserve the diagram above the label, retype the observed label
                # below it; independently cropped label notes are not reprinted.
                box[3] = min(box[3], region.label_box[1] - .012)
            parts.append((region.label, clean.crop(bounds(box, *clean.size))))
        result["crop_asset_id"] = store_image(db, diagram_sheet(parts), "diagram")
        result["print_options_embedded"] = True
        result["diagram_crop_fallback"] = False
        result["diagram_layout"] = "split_options"
        result["image_review_required"] = True
        result["image_processing_concerns"].append("图形与选项编号已分块排版，请校对完整性、编号对应及铅笔残留")
    elif image_options:
        result["crop_asset_id"] = processed_id
        result["image_review_required"] = True
        result["image_processing_concerns"].append(
            "图形选项尚未完整匹配，暂保留整题副本；请多框裁图并核对选项编号与图形匹配后确认打印图"
        )
    elif diagrams:
        result["crop_asset_id"] = (
            diagrams[0] if len(diagrams) == 1 else combine(db, diagrams)
        )
    return result


def inline_asset(db,image,item):
    crop=image.crop(bounds(item.box,*image.size))
    from app.modules.learning.document_cv import normalize_illumination
    crop,_,_=normalize_illumination(crop)
    text_height=max(1,item.line_height*image.height)
    return {'key':item.key,'kind':item.kind,'placement':item.placement,'label':item.label,'box':item.box,'text_height':text_height,'display_width':round(crop.width*20/text_height),'asset_id':store_image(db,crop,'inline_original')}


def inline_assets(db, aid, recognition, ink='off', exclusions=None):
    """Create immutable source crops for version content or a review draft."""
    if not recognition.inline_regions:return []
    image=load_image(db,aid)
    if exclusions:
        from app.modules.learning.note_filter import apply
        image=apply(image,exclusions)
    if ink!='off':
        from app.modules.learning.local_ocr import clean_color_notes
        image,_=clean_color_notes(image,ink)
    return [inline_asset(db,image,item) for item in recognition.inline_regions]
