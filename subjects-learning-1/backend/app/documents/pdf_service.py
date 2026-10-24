import html
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def _font(font_path: str | None) -> str:
    if font_path and Path(font_path).exists():
        name = "LocalCJK"
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, font_path))
        return name
    name = "STSong-Light"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(name))
    return name


def generate_paper_pdf(title: str, items: list[dict], output: Path, font_path: str | None = None, include_answers: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    font = _font(font_path)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName=font, fontSize=10.5, leading=17, spaceAfter=6)
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontName=font, fontSize=18, leading=24, alignment=1, spaceAfter=14)
    story = [Paragraph(html.escape(title), title_style), Paragraph("高中题目学习系统 · 本地生成", body), Spacer(1, 4 * mm)]
    for number, item in enumerate(items, 1):
        content = item.get("content") or {}
        story.append(Paragraph(f"{number}. {html.escape(content.get('stem', '题目内容缺失'))}（{item.get('points', 0):g}分）", body))
        options = content.get("options") or []
        if options:
            story.append(Paragraph("<br/>".join(html.escape(str(option)) for option in options), body))
        if include_answers:
            story.append(Paragraph(f"答案：{html.escape(str(content.get('answer', '待确认')))}", body))
            for step in content.get("solution_steps") or []:
                story.append(Paragraph(f"{step.get('index', '')}. {html.escape(str(step.get('content', '')))}", body))
        else:
            story.append(Spacer(1, 16 * mm))
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    doc.build(story)
