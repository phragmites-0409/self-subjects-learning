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
                # SimHei has no zero-width-space glyph; lineBreak still forces
                # the newline when its placeholder is an ordinary space.
                fragment.text = " "
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
                if formula.startswith(r"\begin{array}"):
                    from app.modules.learning.document_structure import render_plain_array
                    buffer.write(render_plain_array(formula))
                else:
                    from app.modules.learning.formula_rendering import ready,render
                    rendered = False
                    if ready():
                        try:
                            buffer.write(render(formula)[0])
                            rendered = True
                        except (OSError, ValueError, RuntimeError):
                            pass
                    if not rendered:
                        math_to_image("$" + formula.replace("\\dfrac", "\\frac") + "$",buffer,dpi=220,format="png",color="#172936")
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


def export_pdf(db: Session, eid: str, include_answers=False, *, frozen=None) -> Path:
    from types import SimpleNamespace
    from app.modules.learning.service import today
    e = get_event(db, eid) if frozen is None else SimpleNamespace(
        title=frozen["title"], kind="paper", day=today(), minutes=sum(i["data"].get("minutes", 8) for i in frozen["items"]), data={})
    if frozen is None and e.status == "paused":
        fail("题型重推已暂停，请先启用该题型")
    if e.kind not in ("error", "type", "paper"):
        fail("只有推送事项可以导出题目PDF")
    r = get_round(db, e.data["round_id"]) if frozen is None else SimpleNamespace(target=e.day)
    store = LocalFilesystemContentStore()
    cache_key = "answer_pdf_key" if include_answers else "pdf_key"
    existing = e.data.get(cache_key)
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
            "答案解析卷，以出卷时确认内容为准。" if include_answers else "请按本卷题号作答，回收时选择对应事项。原题链接保留出卷版本。",
            small,
        ),
        Spacer(1, 5 * mm),
    ]
    items = db.scalars(
        select(RoundItem).where(RoundItem.event_id == eid).order_by(RoundItem.position)
    ).all() if frozen is None else [SimpleNamespace(**entry) for entry in frozen["items"]]
    def image_block(image):
        aid=image['asset_id']
        asset=db.get(Asset,aid)
        if not asset or asset.deleted_at:fail('原位公式或题图文件缺失','ASSET_MISSING',500)
        with PILImage.open(BytesIO(store.read_bytes(asset.storage_key))) as source_image:
            im=ImageOps.exif_transpose(source_image).convert('RGB');buffer=BytesIO();im.save(buffer,'PNG');width,height=im.size
        scale=min(165*mm/width,140*mm/height)
        if image.get('text_height'):scale=min(scale,14/image['text_height'])
        return Image(BytesIO(buffer.getvalue()),width=width*scale,height=height*scale,hAlign='LEFT')
    previous_section = None
    for number, item in enumerate(items, 1):
        section = item.data.get("section_name")
        if section and section != previous_section:
            story.append(Paragraph(html.escape(section), heading))
            previous_section = section
        link = f"http://127.0.0.1:{get_settings().port}/questions/{item.question_id}?version={item.version_id or ''}"
        story.append(
            Paragraph(
                f'{number}.　{item.data.get("points", "")}分　<a href="{link}" color="#267e73">查看原题（{item.question_id[:8]}）</a>',
                body,
            )
        )
        inline_images=item.data.get('inline_images',item.data.get('content',{}).get('inline_images',[]))
        images={image['key']:image for image in inline_images}
        rendered_diagram=False
        def render_text(text):
            nonlocal rendered_diagram
            markup=[]
            def flush_markup():
                if markup:
                    story.append(Paragraph(''.join(markup),body));markup.clear()
            for part in re.split(r'(\[\[图块:\d+\]\])',text):
                anchor=re.fullmatch(r'\[\[图块:(\d+)\]\]',part)
                if anchor:
                    image=images.get(anchor[1])
                    if not image:fail('原位图块与题干不匹配，请重新校对后组卷','INLINE_IMAGE_MISSING',409)
                    block=image_block(image)
                    if image.get('placement')=='inline':
                        asset=db.get(Asset,image['asset_id']);path=store.path_for(asset.storage_key)
                        markup.append(f'<img src="{html.escape(str(path),quote=True)}" width="{block.drawWidth:.2f}" height="{block.drawHeight:.2f}" valign="middle"/>')
                    else:flush_markup();story.append(block)
                    rendered_diagram=rendered_diagram or image['kind']=='diagram'
                elif part.strip():markup.append(formatted(part,store))
            flush_markup()
        if item.data.get('stem'):render_text(item.data['stem'])
        options = item.data.get("content", {}).get("options", [])
        for option in options:
            if item.data.get("print_options_embedded") and re.fullmatch(r"\s*\[[A-H]\]\s*", str(option)):
                continue
            render_text(str(option))
        crop = item.data.get("crop_asset_id")
        source = item.data.get("source_asset_id")
        # Only user-selected printable crop is inserted when text exists: handwritten notes never silently leak.
        aid = None if inline_images else crop or (source if not item.data.get("stem") else None)
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
        if item.data.get("content", {}).get("has_diagram") and not aid and not rendered_diagram:
            fail(
                "含图题尚未选定打印图像，请先在原题中裁切并保存，再重新生成待出卷安排",
                "DIAGRAM_NOT_CONFIRMED",
                409,
            )
        if include_answers:
            if not item.data.get("answer_confirmed"):
                render_text("本题答案尚需人工核对。")
            render_text("答案：" + (item.data.get("answer") or "见答案图/解析，必要时人工核对"))
            render_text(item.data.get("answer_explanation", ""))
            for aid in item.data.get("answer_asset_ids", []):
                story.append(image_block({"asset_id": aid}))
        else:
            story.append(AnswerSpace(1, item.data.get("answer_space_mm", 30) * mm))
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
    if frozen is None:
        e.data = {**e.data, cache_key: key, "started_day": e.data.get("started_day", today())}
        db.commit()
    return store.path_for(key)
