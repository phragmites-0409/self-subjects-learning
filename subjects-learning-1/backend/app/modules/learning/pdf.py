"""Printable question-only papers with immutable question references and diagram assets."""

import html
import re
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph as ReportParagraph, SimpleDocTemplate, Spacer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.modules.learning.models import RoundItem
from app.modules.learning.service import fail, get_event, get_round, label
from app.storage.local_store import LocalFilesystemContentStore
from app.core.config import get_settings


class Paragraph(ReportParagraph):
    def breakLinesCJK(self, maxWidths):
        # ReportLab's CJK splitter calls ord() on empty inline-image callbacks.
        # A nonprinting object marker keeps the callback width and image drawing
        # intact, and prevents the splitter from treating it as an empty glyph.
        for fragment in self.frags:
            if getattr(fragment, "text", None) == "" and hasattr(fragment, "cbDefn"):
                fragment.text = "\ufffc"
            elif getattr(fragment, "text", None) == "" and hasattr(fragment, "lineBreak"):
                fragment.text = "\u200b"
        return super().breakLinesCJK(maxWidths)


class AnswerSpace(Spacer):
    def wrap(self, availWidth, availHeight):
        return self.width, min(self.height, max(0, availHeight))


SUBS = dict(zip("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎", "0123456789+-=()"))
SUPERS = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾", "0123456789+-=()"))


def plain_markup(text):
    output = []
    for char in text:
        if char in SUBS:
            output.append(f"<sub>{SUBS[char]}</sub>")
        elif char in SUPERS:
            output.append(f"<super>{SUPERS[char]}</super>")
        else:
            output.append(html.escape(char).replace("\n", "<br/>"))
    return "".join(output)


def formatted(text: str, store: LocalFilesystemContentStore) -> str:
    """Render supported LaTeX to a sharp transparent inline asset; retain unsupported source text."""
    from matplotlib.mathtext import math_to_image

    parts = re.split(
        r"(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\))", text
    )
    output = []
    for part in parts:
        if part.startswith(("$", "\\[", "\\(")):
            formula = (
                part[2:-2] if part.startswith(("$$", "\\[", "\\(")) else part[1:-1]
            )
            try:
                buffer = BytesIO()
                math_to_image(
                    "$" + formula.replace("\\dfrac", "\\frac") + "$",
                    buffer,
                    dpi=220,
                    format="png",
                    color="#172936",
                )
                key, _ = store.put_bytes("thumbnails", buffer.getvalue(), ".png")
                with PILImage.open(BytesIO(buffer.getvalue())) as image:
                    width, height = image.size
                scale = min(72 / 220, 470 / width)
                output.append(
                    f'<img src="{html.escape(str(store.path_for(key)), quote=True)}" width="{width * scale:.2f}" height="{height * scale:.2f}" valign="middle"/>'
                )
            except (ValueError, RuntimeError):
                output.append(html.escape(part))
        else:
            output.append(plain_markup(part))
    return "".join(output)


def export_pdf(db: Session, eid: str) -> Path:
    e = get_event(db, eid)
    if e.kind not in ("error", "type"):
        fail("只有推送事项可以导出题目PDF")
    r = get_round(db, e.data["round_id"])
    store = LocalFilesystemContentStore()
    existing = e.data.get("pdf_key")
    if existing and store.path_for(existing).exists():
        return store.path_for(existing)
    font = "LearningCJK"
    if font not in pdfmetrics.getRegisteredFontNames():
        path = Path("C:/Windows/Fonts/simhei.ttf")
        if path.exists():
            pdfmetrics.registerFont(TTFont(font, str(path)))
        else:
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont

            font = "STSong-Light"
            pdfmetrics.registerFont(UnicodeCIDFont(font))
    body = ParagraphStyle(
        "LearningBody",
        fontName=font,
        fontSize=11,
        leading=20,
        wordWrap="CJK",
        spaceAfter=6,
        autoLeading="max",
    )
    small = ParagraphStyle(
        "LearningSmall", parent=body, fontSize=8, leading=13, textColor="#587176"
    )
    heading = ParagraphStyle(
        "LearningHeading", parent=body, fontSize=18, leading=27, spaceAfter=10
    )
    story = [
        Paragraph(html.escape(e.title), heading),
        Paragraph(
            f"安排：{label(e.day)}　目标：{label(r.target)}　预计：{e.minutes:g}分钟",
            small,
        ),
        Paragraph(
            "只含题目。请按本卷题号作答，回收时选择对应事项。原题链接保留出卷版本。",
            small,
        ),
        Spacer(1, 5 * mm),
    ]
    items = db.scalars(
        select(RoundItem).where(RoundItem.event_id == eid).order_by(RoundItem.position)
    ).all()
    for number, item in enumerate(items, 1):
        link = f"http://127.0.0.1:{get_settings().port}/questions/{item.question_id}?version={item.version_id or ''}"
        story.append(
            Paragraph(
                f'{number}.　<a href="{link}" color="#267e73">查看原题（{item.question_id[:8]}）</a>',
                body,
            )
        )
        if item.data.get("stem"):
            story.append(Paragraph(formatted(item.data["stem"], store), body))
        options = item.data.get("content", {}).get("options", [])
        for option in options:
            if item.data.get("print_options_embedded") and re.fullmatch(r"\s*\[[A-H]\]\s*", str(option)):
                continue
            story.append(Paragraph(formatted(str(option), store), body))
        crop = item.data.get("crop_asset_id")
        source = item.data.get("source_asset_id")
        # Only user-selected printable crop is inserted when text exists: handwritten notes never silently leak.
        aid = crop or (source if not item.data.get("stem") else None)
        if aid:
            asset = db.get(Asset, aid)
            if not asset:
                fail("原题图像文件缺失", "ASSET_MISSING", 500)
            with PILImage.open(BytesIO(store.read_bytes(asset.storage_key))) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                buffer = BytesIO()
                im.save(buffer, "PNG")
                width, height = im.size
            scale = min(165 * mm / width, 140 * mm / height)
            story.append(
                Image(
                    BytesIO(buffer.getvalue()),
                    width=width * scale,
                    height=height * scale,
                    hAlign="LEFT",
                )
            )
        if item.data.get("content", {}).get("has_diagram") and not aid:
            fail(
                "含图题尚未选定打印图像，请先在原题中裁切并保存，再重新生成待出卷安排",
                "DIAGRAM_NOT_CONFIRMED",
                409,
            )
        story.append(AnswerSpace(1, 30 * mm))
    buffer = BytesIO()

    def footer(canvas, doc):
        canvas.setFont(font, 8)
        canvas.drawString(18 * mm, 10 * mm, f"题研 · 事项 {eid[:8]} · {label(e.day)}")
        canvas.drawRightString(192 * mm, 10 * mm, f"第{doc.page}页")

    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    key, _ = store.put_bytes("generated-pdfs", buffer.getvalue(), ".pdf")
    e.data = {**e.data, "pdf_key": key}
    db.commit()
    return store.path_for(key)
