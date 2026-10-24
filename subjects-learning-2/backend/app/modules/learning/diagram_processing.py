"""Local pencil attenuation and explicit pixel edits. Originals remain immutable."""
import math
from PIL import Image, ImageDraw, ImageFont
from app.core.errors import AppError

PENCIL_MODES = {"off", "gentle", "balanced", "strong"}


def pencil_cleanup(image, mode="balanced"):
    if mode not in PENCIL_MODES:
        raise AppError("INVALID_IMAGE_MODE", "请选择有效的铅笔处理强度", 422)
    if mode == "off":
        return image.copy(), {"pencil_mode": mode, "pencil_changed_pixels": 0}
    import cv2
    import numpy as np
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    kernel = min(61, max(3, min(image.size) // 8 * 2 + 1))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    background = cv2.GaussianBlur(background, (0, 0), max(1, kernel / 5))
    normalized = cv2.divide(gray, np.maximum(background, 1), scale=255)
    # This attenuates light graphite by contrast, not by deciding which marks
    # are handwriting. Dark pencil and faint printed marks remain ambiguous.
    white = {"gentle": 218, "balanced": 188, "strong": 165}[mode]
    clean = np.clip((normalized.astype(np.float32) - 70) * 255 / (white - 70), 0, 255).astype(np.uint8)
    # Preserve observed very dark thin strokes and their antialiased boundaries.
    core = cv2.dilate((normalized < 80).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    clean[core] = np.minimum(clean[core], normalized[core])
    return Image.fromarray(clean).convert("RGB"), {
        "pencil_mode": mode, "pencil_changed_pixels": int(np.count_nonzero(clean.astype(np.int16) > normalized.astype(np.int16) + 5)),
        "image_review_required": True,
    }


def stroke_mask(image, strokes):
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 200:
        raise AppError("INVALID_IMAGE_MASK", "请标记笔迹区域", 422)
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    total = 0
    for stroke in strokes:
        if not isinstance(stroke, dict):
            raise AppError("INVALID_IMAGE_MASK", "笔迹区域无效", 422)
        points, radius = stroke.get("points"), stroke.get("radius")
        if isinstance(radius, bool) or not isinstance(radius, (float, int)) or not math.isfinite(radius) or not .001 <= radius <= .05:
            raise AppError("INVALID_IMAGE_MASK", "画笔大小无效", 422)
        if not isinstance(points, list) or not 1 <= len(points) <= 3000:
            raise AppError("INVALID_IMAGE_MASK", "笔迹路径无效", 422)
        total += len(points)
        if total > 30000:
            raise AppError("INVALID_IMAGE_MASK", "笔迹路径过长，请分次处理", 422)
        scaled = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
                raise AppError("INVALID_IMAGE_MASK", "坐标必须在图像范围内", 422)
            scaled.append((round(point[0] * (image.width - 1)), round(point[1] * (image.height - 1))))
        r = max(1, round(radius * image.width))
        if len(scaled) > 1:
            draw.line(scaled, fill=255, width=2 * r + 1, joint="curve")
        for x, y in scaled:
            draw.ellipse((x-r, y-r, x+r, y+r), fill=255)
    return mask


def erase_strokes(image, strokes, method="white", protect_strokes=None):
    if method not in {"white", "inpaint", "lama", "handwriting"}:
        raise AppError("INVALID_IMAGE_MASK", "请选择有效的擦除方式", 422)
    mask = stroke_mask(image, strokes)
    if protect_strokes is not None:
        if not isinstance(protect_strokes, list):
            raise AppError("INVALID_IMAGE_MASK", "保护笔迹格式无效", 422)
        if protect_strokes:
            from PIL import ImageChops
            mask = ImageChops.subtract(mask, stroke_mask(image, protect_strokes))
    if not mask.getbbox():
        raise AppError("EMPTY_IMAGE_MASK", "擦除区域全部被保护，请调整笔刷范围", 422)
    if method == "handwriting":
        from app.modules.learning.ink_segmentation import refine
        mask=refine(image,mask)
    if method == "white":
        clean = image.copy()
        clean.paste("white", mask=mask)
    elif method in {"inpaint","handwriting"}:
        import cv2
        import numpy as np
        clean = Image.fromarray(cv2.inpaint(np.asarray(image.convert("RGB")), np.asarray(mask), 3, cv2.INPAINT_NS))
    else:
        from app.modules.learning.diagram_repair import repair
        clean = repair(image, mask)
    return clean, mask


def diagram_sheet(parts):
    """Keep explicitly paired labels and diagrams together without original notes."""
    main = [image for label, image in parts if not label]
    options = [(label, image) for label, image in parts if label]
    if not options:
        width = max(image.width for image in main)
        height = sum(image.height for image in main) + 16 * max(0, len(main)-1)
    else:
        cell_width = max(image.width for _, image in options)
        cell_height = max(image.height for _, image in options) + 50
        width = max([2 * cell_width + 32, *[image.width for image in main]])
        height = sum(image.height + 20 for image in main) + math.ceil(len(options)/2) * (cell_height + 16)
    if width * height > 40_000_000:
        raise AppError("IMAGE_TOO_LARGE", "裁图组合过大，请减少图块", 422)
    result = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(result)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default(size=28)
    top = 0
    for image in main:
        result.paste(image, ((width-image.width)//2, top))
        top += image.height + 20
    for index, (label, image) in enumerate(options):
        x = (index % 2) * (cell_width + 32)
        y = top + (index // 2) * (cell_height + 16)
        result.paste(image, (x + (cell_width-image.width)//2, y))
        draw.text((x + cell_width//2, y + cell_height - 30), f"[{label}]", fill="black", font=font, anchor="mm")
    return result
