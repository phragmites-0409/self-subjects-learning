from io import BytesIO

from PIL import Image, ImageOps

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


def normalize_image(data: bytes, max_dimension: int = 2400, quality: int = 88) -> tuple[bytes, bytes, int, int]:
    with Image.open(BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        width, height = image.size
        output = BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        preview = image.copy()
        preview.thumbnail((640, 640), Image.Resampling.LANCZOS)
        preview_output = BytesIO()
        preview.save(preview_output, format="WEBP", quality=76, method=6)
        return output.getvalue(), preview_output.getvalue(), width, height
