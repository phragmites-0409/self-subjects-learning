"""Offline OCR and page geometry. Model downloads are an explicit setup step."""

import base64
import importlib.util
import json
import math
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageOps

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.runtime import RUNTIME_ROOT, read_manifest

LOCK = threading.RLock()
OPTION = re.compile(r"^\s*[\[（(]?([A-H])[\]）).．、]\s*(.*)$")
NUMBER = re.compile(r"^\s*(?:第\s*)?(\d{1,3})(?:题)?[.．、)）](?!\d)\s*(.*)$")
BRACKET_NUMBER = re.compile(r"^\s*[【\[]([0-9]{1,3})[】\]]\s*(.*)$")
CHAPTER = re.compile(
    r"^(?:第[一二三四五六七八九十百\d]+[章节单元]|[一二三四五六七八九十]+、)"
)


def manifest_path() -> Path:
    local = get_settings().data_dir / "models" / "local-ocr" / "manifest.json"
    return local if local.is_file() else RUNTIME_ROOT / "models/local-ocr/manifest.json"


def status() -> dict:
    installed = all(
        importlib.util.find_spec(name)
        for name in ("rapidocr", "rapid_layout", "cv2", "onnxruntime")
    )
    if not installed or not manifest_path().is_file():
        return {
            "ready": False,
            "formula_ready": False,
            "message": "本地识别尚未准备好，请先运行本地识别安装脚本",
        }
    try:
        manifest = read_manifest(manifest_path())
        required = [
            manifest["ocr"][f"{part}.model_path"] for part in ("Det", "Cls", "Rec")
        ]
        required.append(manifest["layout"]["model_dir_or_path"])
        ready = all(Path(value).is_file() for value in required)
        formula_ready = (
            bool(manifest.get("formula"))
            and Path(manifest.get("formula_python", "")).is_file()
            and all(Path(value).is_file() for value in manifest["formula"].values())
        )
        return {
            "ready": ready,
            "formula_ready": formula_ready,
            "message": "本地识别已就绪，图片处理不调用外部API"
            if ready
            else "本地模型文件不完整，请重新准备模型",
        }
    except (ValueError, KeyError, TypeError, OSError):
        return {
            "ready": False,
            "formula_ready": False,
            "message": "本地模型配置无法读取，请重新准备模型",
        }


def clean_color_notes(image: Image.Image, mode: str = "red") -> tuple[Image.Image, int]:
    if mode == "off":
        return image.copy(), 0
    import cv2
    import numpy as np

    rgb = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, saturation, value = (hsv[:, :, i] for i in range(3))
    # Avoid selecting dark printed strokes and the warm colour of photographed paper.
    red = ((hue <= 15) | (hue >= 165)) & (saturation > 25) & (value > 35)
    red &= rgb[:, :, 0].astype(int) - rgb[:, :, 1].astype(int) > 15
    red &= rgb[:, :, 0].astype(int) - rgb[:, :, 2].astype(int) > 12
    mask = red
    if mode == "red_blue":
        mask = mask | ((hue >= 100) & (hue <= 135) & (saturation > 75) & (value > 100))
    count = int(mask.sum())
    if not count:
        return image.copy(), 0
    # Change selected ink pixels only, never a rectangle containing printed text.
    repaired = cv2.inpaint(rgb, mask.astype("uint8") * 255, 2, cv2.INPAINT_TELEA)
    return Image.fromarray(repaired), count


@dataclass
class Line:
    text: str
    box: list[float]
    score: float = 1.0
    text_height: float | None = None
    quad: list[list[float]] | None = None
    words: list[dict] | None = None


def glyph_height(points,height):
    """Short edges of the OCR quadrilateral, unaffected by a sloping long row."""
    return max(.001,(math.hypot(*(points[3]-points[0]))+math.hypot(*(points[2]-points[1])))/2/height)


def word_geometry(result,index,size):
    import numpy as np
    words=getattr(result,'word_results',None)
    if not words or index>=len(words):return None
    output=[]
    for text,score,points in words[index]:
        if points is None:continue
        quad=np.asarray(points,np.float32)/np.array(size,np.float32)
        output.append({'text':text,'score':float(score),'quad':quad.tolist(),'box':[float(quad[:,0].min()),float(quad[:,1].min()),float(quad[:,0].max()),float(quad[:,1].max())]})
    return output


def region(box, width, height, padding=0) -> list[float]:
    left, top, right, bottom = (float(v) for v in box)
    if not all(math.isfinite(v) for v in (left, top, right, bottom)):
        raise AppError("LOCAL_OCR_BAD_BOX", "本地识别返回无效区域，请手动核对", 502)
    return [
        max(0, (left - padding) / width),
        max(0, (top - padding) / height),
        min(1, (right + padding) / width),
        min(1, (bottom + padding) / height),
    ]


def inside(box, outer, padding=0) -> bool:
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return outer[0]-padding <= x <= outer[2]+padding and outer[1]-padding <= y <= outer[3]+padding


def contained(box, outer, padding=.015):
    return box[0]>=outer[0]-padding and box[1]>=outer[1]-padding and box[2]<=outer[2]+padding and box[3]<=outer[3]+padding


class Runtime:
    def __init__(self, manifest):
        from rapid_layout import RapidLayout
        from rapidocr import RapidOCR

        self.ocr = RapidOCR(params={**manifest["ocr"], 'Global.return_word_box':True, 'Global.return_single_char_box':True})
        self.layout = RapidLayout(**manifest["layout"])
        self.formula_config = manifest.get("formula")
        self.formula_python = manifest.get("formula_python")

    def read(self, image, formula=True, pencil="off", question=False, semantic_image=None):
        import numpy as np

        enhanced = ImageOps.autocontrast(image, cutoff=0.2, preserve_tone=True)
        bgr = np.asarray(enhanced)[:, :, ::-1].copy()
        layout = self.layout(bgr)
        elements = []
        for box, label, score in zip(
            layout.boxes if layout.boxes is not None else [],
            layout.class_names if layout.class_names is not None else [],
            layout.scores if layout.scores is not None else [],
            strict=True,
        ):
            if float(score) >= 0.5:
                elements.append(
                    {
                        "box": region(box, *image.size),
                        "label": label,
                        "score": float(score),
                    }
                )
        # Detect geometry on the photograph, before suppressing graphite. Faint
        # dashed curves and labels must not disappear from layout detection.
        from app.modules.learning.ink_segmentation import configuration as ink_configuration
        # Semantic classification can separate handwriting without destroying
        # faint printed subscripts, question numbers and fraction rules first.
        semantic_text=False
        text_image, pencil_info = question_text_image(image, pencil)
        if not pencil_info["filtered"]:
            text_image = enhanced.copy()
        if pencil_info["filtered"]:
            for element in elements:
                if element["label"] in ("figure", "image", "chart", "table", "formula", "isolate_formula", "isolated_formula", "display_formula", "equation"):
                    box = element["box"]
                    coordinates = (int(max(0,box[0]-.012)*image.width), int(max(0,box[1]-.012)*image.height), math.ceil(min(1,box[2]+.012)*image.width), math.ceil(min(1,box[3]+.012)*image.height))
                    text_image.paste(enhanced.crop(coordinates), coordinates[:2])
        result = self.ocr(np.asarray(text_image)[:, :, ::-1].copy())
        lines = []
        if result.boxes is not None:
            for index,(points, text, score) in enumerate(zip(
                result.boxes, result.txts, result.scores, strict=True
            )):
                xs, ys = points[:, 0], points[:, 1]
                lines.append(
                    Line(
                        text.strip(),
                        region([xs.min(), ys.min(), xs.max(), ys.max()], *image.size),
                        float(score),
                        glyph_height(points,image.height),
                        (points / np.array([image.width,image.height])).tolist(),
                        word_geometry(result,index,image.size),
                    )
                )
        if pencil_info["filtered"] and sum(e["label"] in ("figure", "image", "chart") for e in elements) >= 2:
            # Picture-choice labels can be gray or circled. Recover observed
            # bare labels from the original, never its handwritten body text.
            original_result = self.ocr(bgr)
            if original_result.boxes is not None:
                for points, text, score in zip(original_result.boxes, original_result.txts, original_result.scores, strict=True):
                    text = text.strip()
                    match = OPTION.match(text)
                    if not (match and not match.group(2).strip() or re.fullmatch(r"[A-H]", text)):
                        continue
                    xs, ys = points[:, 0], points[:, 1]
                    box = region([xs.min(), ys.min(), xs.max(), ys.max()], *image.size)
                    if not any(inside(box, existing.box) for existing in lines):
                        lines.append(Line(text, box, float(score)))
        concerns = []
        if question and ink_configuration() is not None and any(re.search(r'反应|Arrhenius|热化学|数列|矩阵',line.text) for line in lines):
            semantic_text=True
            original_result=self.ocr(bgr)
            if original_result.boxes is not None:
                lines=[]
                for index,(points,text,score) in enumerate(zip(original_result.boxes,original_result.txts,original_result.scores,strict=True)):
                    xs,ys=points[:,0],points[:,1]
                    lines.append(Line(text.strip(),region([xs.min(),ys.min(),xs.max(),ys.max()],*image.size),float(score),glyph_height(points,image.height),(points/np.array([image.width,image.height])).tolist(),word_geometry(original_result,index,image.size)))
        if semantic_text:concerns.append('文字识别保留原始印刷灰度，笔记由专用模型分类筛除，避免阈值处理损伤上下标')
        if question and image.width*image.height>=100000:
            from app.modules.learning.ink_segmentation import page_probabilities
            from app.modules.learning.printed_document import filter_printed
            original=semantic_image if semantic_image is not None else image
            lines,elements,messages=filter_printed(original,lines,elements,page_probabilities(original))
            concerns.extend(messages)
        from app.modules.learning.document_structure import detect_grids, grid_content
        for grid in detect_grids(enhanced):
            element, latex = grid_content(lines, grid, image.size)
            # Replace incomplete table/figure fragments with the whole detected grid.
            elements = [existing for existing in elements if not (existing["label"] in ("figure", "image", "chart", "table") and inside(existing["box"],element["box"]))]
            elements.append(element)
            if latex:
                lines = [line for line in lines if not inside(line.box,element["box"])]
                lines.append(Line(f"${latex}$",element["box"]))
                concerns.append("规则表格已按单元格转录，请核对行列、数值和合并单元格")
            else:
                concerns.append("网格曲线图或复杂表格保留为完整图块，坐标、表头与标注不混入题干")
        if question:
            # Ordinary OCR flattens reaction subscripts and stacked coefficients.
            # Retain the printed reaction row, rather than treating that output
            # as a faithful formula transcription.
            for line in lines:
                reaction_row = line.score >= .85 and re.match(r"^反应", line.text) and re.search(r"[CHON][0-9₀-₉]|\([gls]\)", line.text)
                numbered_reaction = re.match(r"^[①②③④⑤⑥⑦⑧⑨]", line.text) and re.search(r"[CHO][0-9₀-₉]|[→⇒]", line.text)
                stacked_formula = "Arrhenius" in line.text and "公式" in line.text
                if reaction_row or numbered_reaction or stacked_formula:
                    box = line.box
                    padding = .025 if reaction_row or stacked_formula else .012
                    right = box[2]
                    if stacked_formula:
                        right = max([right]+[other.box[2] for other in lines if abs((other.box[1]+other.box[3]-box[1]-box[3])/2)<.035])
                    elements.append({"label":"isolate_formula", "box":[max(0,box[0]-.004),max(0,box[1]-padding),min(1,right+.004),min(1,box[3]+padding)], "score":line.score, "preserve_image":True})
                    concerns.append("化学反应式保留原图公式块，避免普通文字识别丢失上下标、分数和反应箭头")
            from app.modules.learning.printed_text_filter import filter_notes
            lines,notes=filter_notes(lines,elements)
            elements.extend(notes)
            if notes:concerns.append(f"已排除{len(notes)}个正文行外的疑似手写计算区域；深色重叠笔记仍须框选或局部修复")
        if pencil_info["filtered"] and not semantic_text:
            concerns.append("文字识别前已抑制浅灰笔迹；浅色印刷文字也可能受影响，请对照原图核对。图形与独立公式保留原图识别")
        elif pencil != "off" and not semantic_text:
            concerns.append("印刷对比不足，未强行过滤灰色文字，请局部擦除笔迹后重新提取文字")
        if formula and self.formula_config and self.formula_python:
            for element in elements:
                if element["label"] not in (
                    "formula",
                    "isolated_formula",
                    "isolate_formula",
                    "display_formula",
                    "equation",
                ):
                    continue
                if element.get("preserve_image"):
                    continue
                box = element["box"]
                crop = image.crop(
                    (
                        int(box[0] * image.width),
                        int(box[1] * image.height),
                        math.ceil(box[2] * image.width),
                        math.ceil(box[3] * image.height),
                    )
                )
                buf = BytesIO()
                crop.save(buf, "PNG")
                try:
                    worker = (
                        Path(__file__).resolve().parents[4]
                        / "scripts"
                        / "local-formula-worker.py"
                    )
                    result = subprocess.run(
                        [self.formula_python, str(worker)],
                        input=json.dumps(
                            {
                                "config": self.formula_config,
                                "image": base64.b64encode(buf.getvalue()).decode(
                                    "ascii"
                                ),
                            }
                        ),
                        encoding="utf-8",
                        capture_output=True,
                        timeout=45,
                        check=True,
                        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    latex = json.loads(result.stdout)["text"]
                except (subprocess.SubprocessError, ValueError, KeyError, OSError):
                    concerns.append(
                        "本地公式转录未完成，已保留普通识别文字与原图，请手动核对"
                    )
                    continue
                if reliable_formula(latex):
                    lines = [line for line in lines if not inside(line.box, box)]
                    lines.append(Line(f"${latex}$", box))
                    concerns.append("公式由本地模型转录，请核对上下标、符号和单位")
                else:
                    concerns.append("公式输出重复或结构异常，已保留原图公式块，请校对")
        elif formula:
            concerns.append("本地公式模型未准备好，公式保留普通识别文字和原图，请核对")
        return (
            sorted(lines, key=lambda line: (line.box[1], line.box[0])),
            elements,
            concerns,
        )


def reliable_formula(latex):
    if not isinstance(latex,str) or not latex.strip() or len(latex)>1500:
        return False
    depth=0
    for char in latex:
        if char=="{":depth+=1
        elif char=="}":depth-=1
        if depth<0:return False
    if depth:return False
    return not any(len(re.findall(re.escape(command),latex))>8 for command in (r"\underbrace",r"\overbrace",r"\Delta",r"\left",r"\right"))


@lru_cache(maxsize=1)
def runtime(path: str):
    if not status()["ready"]:
        raise AppError("LOCAL_OCR_NOT_READY", status()["message"], 409)
    manifest = read_manifest(path)
    # Explicit existing model paths prevent library constructors from downloading at runtime.
    return Runtime(manifest)


def question_text_image(image, pencil="balanced"):
    """Question text only; this is contrast separation, not a handwriting model."""
    from app.modules.learning.diagram_processing import PENCIL_MODES
    if pencil not in PENCIL_MODES:
        raise AppError("INVALID_IMAGE_MODE", "请选择有效的铅笔处理强度", 422)
    if pencil == "off":
        return image.copy(), {"filtered": False}
    import cv2
    import numpy as np
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    size = min(61, max(3, min(image.size)//8*2+1))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
    normalized = cv2.divide(gray, np.maximum(background, 1), scale=255)
    ink = normalized[normalized < 210]
    # A faded original must remain available rather than becoming blank text.
    if not ink.size or np.percentile(ink, 10) > 140:
        return image.copy(), {"filtered": False}
    cutoff = {"gentle": 140, "balanced": 120, "strong": 100}[pencil]
    clean = np.where(normalized < cutoff, 0, 255).astype(np.uint8)
    return Image.fromarray(clean).convert("RGB"), {"filtered": True}


def read(raw: bytes, ink="red", formula=True, pencil="off", question=False):
    started = time.perf_counter()
    with Image.open(BytesIO(raw)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
    semantic_image=image.copy()
    image, removed = clean_color_notes(image, ink)
    with LOCK:
        lines, elements, concerns = runtime(str(manifest_path().resolve())).read(
            image, formula, pencil, question, semantic_image
        )
    if removed:
        concerns.append("已按颜色清理笔迹，请核对原题中的彩色标注；原图保留")
    if any(line.score < 0.85 for line in lines):
        concerns.append("部分文字识别置信度较低，请核对数字、公式和单位")
    return (
        lines,
        elements,
        concerns,
        {
            "engine": "local",
            "seconds": round(time.perf_counter() - started, 2),
            "color_pixels": removed,
            "ink": ink,
            "text_pencil_mode": pencil,
        },
    )


def question_from_lines(lines: list[Line], elements: list[dict], hint="") -> dict:
    formula_labels = {
        "formula",
        "isolated_formula",
        "isolate_formula",
        "display_formula",
        "equation",
    }
    preserved_formulas = [
        element
        for element in elements
        if element["label"] in formula_labels
        and not any(
            line.text.startswith("$") and inside(line.box, element["box"])
            for line in lines
        )
    ]
    figures = [
        dict(element)
        for element in elements
        if element["label"] in ("figure", "image", "chart", "table")
    ]
    figures += [dict(element) for element in preserved_formulas]
    options = []
    selected = []
    explicit_labels = [line for line in lines if OPTION.match(line.text)]
    # A detached H./H(...) in a chemistry calculation is not evidence of an
    # eight-choice question. Require another option or explicit bracketed H.
    peer_letters = {OPTION.match(line.text).group(1) for line in explicit_labels}
    for line in lines:
        match = OPTION.match(line.text)
        if match and match.group(1)=="H" and len(peer_letters)==1 and not re.match(r"^\s*\[H\]",line.text):
            match = None
        if not match and re.fullmatch(r"[A-H]", line.text) and line.score >= 0.85:
            # OCR may drop brackets obscured by notes. Accept an observed letter
            # only beside a figure and aligned with another printed option label.
            aligned = any(
                abs(other.box[1] - line.box[1]) <= 0.06 for other in explicit_labels
            )
            beside = any(
                fig["box"][0] <= (line.box[0] + line.box[2]) / 2 <= fig["box"][2]
                and -0.03 <= line.box[1] - fig["box"][3] <= 0.09
                for fig in figures
            )
            if aligned and beside:
                match = OPTION.match(f"[{line.text}]")
        if match:
            letter, text = match.groups()
            options.append((letter, f"[{letter}] {text}".strip()))
            selected.append(line)
            # Printed labels just outside a figure must be included in its crop.
            nearby = [
                fig
                for fig in figures
                if not text.strip() and fig["box"][0] <= (line.box[0] + line.box[2]) / 2 <= fig["box"][2]
                and -0.03 <= line.box[1] - fig["box"][3] <= 0.09
            ]
            if nearby:
                fig = min(nearby, key=lambda f: abs(line.box[1] - f["box"][3]))
                fig["option_label"] = letter
                fig["label_box"] = line.box
                fig["box"] = [
                    min(fig["box"][0], line.box[0]),
                    min(fig["box"][1], line.box[1]),
                    max(fig["box"][2], line.box[2]),
                    max(fig["box"][3], line.box[3]),
                ]
    graphic_options = len(options) >= 2 and all(
        re.fullmatch(r"\[[A-H]\]", text) for _letter, text in options
    )
    # Recover a missing grid cell only from an observed printed label and a
    # detected peer in the same row. The inferred box is explicitly reviewable.
    inferred = False
    if graphic_options:
        paired = {fig.get("option_label") for fig in figures}
        for label_line in selected:
            match = OPTION.match(label_line.text) or OPTION.match(f"[{label_line.text}]")
            if not match or match.group(1) in paired:
                continue
            peers = [fig for fig in figures if fig.get("label_box") and abs(fig["label_box"][1] - label_line.box[1]) < .07]
            if len(peers) != 1:
                continue
            peer = peers[0]
            shift = (label_line.box[0]+label_line.box[2]-peer["label_box"][0]-peer["label_box"][2])/2
            box = peer["box"]
            inferred_box = [max(0, box[0]+shift), box[1], min(1, box[2]+shift), max(box[3], label_line.box[3])]
            if inferred_box[2]-inferred_box[0] >= .1:
                figures.append({"label":"figure", "box":inferred_box, "option_label":match.group(1), "label_box":label_line.box})
                paired.add(match.group(1)); inferred = True
    # Continuations directly below textual options belong to those options,
    # not the stem. Require a nearby row and aligned left edge; never swallow
    # a detached calculation elsewhere on the page.
    if not graphic_options:
        anchors = list(selected)
        for line in lines:
            if line in selected or any(contained(line.box, fig["box"]) for fig in figures):
                continue
            candidates = [(i, anchor) for i, anchor in enumerate(anchors)
                if OPTION.match(anchor.text) and OPTION.match(anchor.text).group(2).strip()
                and -.01 <= line.box[1]-anchor.box[3] <= max(.035, (anchor.box[3]-anchor.box[1])*.8)
                and abs(line.box[0]-anchor.box[0]) < .07]
            if candidates:
                i, anchor = min(candidates, key=lambda item: abs(line.box[1]-item[1].box[3]))
                options[i] = (options[i][0], options[i][1] + line.text)
                # Extend the local anchor for multi-line choices without mutating OCR boxes.
                anchors[i] = Line(anchor.text, [anchor.box[0], anchor.box[1], max(anchor.box[2],line.box[2]),line.box[3]], anchor.score)
                selected.append(line)
    first_label_top = min((line.box[1] for line in selected), default=1)
    from app.modules.learning.reading_order import paragraphs
    stem = paragraphs([
        line
        for line in lines
        if line not in selected
        and not any(contained(line.box, fig["box"]) for fig in figures)
        and not (
            graphic_options
            and re.fullmatch(r"[xyOz]", line.text)
            and line.box[1] > first_label_top - 0.2
        )
    ])
    concerns = []
    if inferred:
        concerns.append("部分选项图框依据已识别编号和同排邻图补齐，请核对边界；未生成缺失图形")
    if preserved_formulas:
        concerns.append(
            "未转录的独立公式保留原图区域用于打印，请核对裁切范围；行内公式仍需核对文字"
        )
    letters = [letter for letter, _text in options]
    if letters:
        missing = [
            chr(code)
            for code in range(ord("A"), ord(max(letters)) + 1)
            if chr(code) not in letters
        ]
        if missing:
            concerns.append(
                f"选项编号未完整识别（缺少{'、'.join(missing)}），请对照原图补全，未猜测缺失内容"
            )
    if not stem.strip():
        stem = hint.strip()
        concerns.append("未识别出完整题干，请对照原图手动校对")
    if figures:
        concerns.append("图形区域来自本地版面检测，请核对边界及选项编号")
    concerns.append("灰色铅笔可减淡；深色笔迹与印刷内容重叠时需局部标记并校对")
    ordered = sorted(
        figures, key=lambda fig: (round(fig["box"][1] / 0.05), fig["box"][0])
    )
    inline_regions=[]
    if not options:
        from app.modules.learning.printed_document import source_layout
        layout=source_layout(lines,[fig for fig in figures if fig['label'] not in formula_labels])
        if layout and layout[1]:
            stem,inline_regions=layout
            ordered=[fig for fig in ordered if fig['label'] not in formula_labels]
    return {
        "stem": stem,
        "options": [text for _letter, text in sorted(options)],
        "has_diagram": bool(ordered) if inline_regions else bool(figures),
        "diagram_regions": [
            {
                "label": fig.get("option_label", ""),
                "label_box": fig.get("label_box"),
                "box": [
                    max(0, b[0] - 0.006),
                    max(0, b[1] - 0.006),
                    min(1, b[2] + 0.006),
                    min(1, b[3] + 0.006),
                ]
            }
            for fig in ordered[:20]
            for b in [fig["box"]]
        ],
        "handwriting_regions": [{"box":element["box"]} for element in elements if element["label"]=="handwriting"],
        "inline_regions":inline_regions,
        "concerns": concerns,
    }


def recognize(raw, hint, ink, formula, pencil="balanced", *, structured=False, threshold=.985):
    from app.modules.learning.subject_detection import detect_subject

    lines, elements, concerns, metadata = read(raw, ink, formula, pencil, question=True)
    result = question_from_lines(lines, elements, hint)
    if structured:
        from app.modules.learning.local_document_ocr import status as document_status
        if document_status()['ready']:
            from app.modules.learning.structured_ocr import transcribe
            with Image.open(BytesIO(raw)) as original:
                image=ImageOps.exif_transpose(original).convert('RGB')
            image,_=clean_color_notes(image,ink)
            rich=transcribe(image,lines,elements,result,threshold)
            if rich:
                metadata['structured']=rich.pop('structured_info')
                metadata['seconds']+=metadata['structured']['seconds']
                concerns=[note for note in concerns if '公式保留原图' not in note]
                result['concerns']=[note for note in result['concerns'] if '未转录的独立公式' not in note]
                result={**result,**{key:value for key,value in rich.items() if key!='concerns'},'concerns':result['concerns']+rich['concerns']}
        else:concerns.append('高精度本地文档模型未安装，使用原图公式块；未调用外部API')
    first_option = min((line.box[1] for line in lines if OPTION.match(line.text)), default=0)
    metadata["leading_text"] = "\n".join(line.text for line in lines if line.box[3] <= first_option and not any(contained(line.box, figure["box"]) for figure in elements if figure["label"] in ("figure", "image", "chart", "table")))
    detection = detect_subject('\n'.join(line.text for line in lines), result["options"])
    metadata['subject_text']='\n'.join(line.text for line in lines)[:12000]
    result["subject"] = detection["subject"]
    metadata["subject_detection"] = detection
    result["concerns"] = list(dict.fromkeys(concerns + result["concerns"]))
    result["metadata"] = metadata
    return result


def supplied_answer(raw, formula):
    # Human-provided answers must keep handwriting; no erasure, solving or judging.
    lines, _elements, concerns, metadata = read(raw, "off", formula)
    return {
        "answer": "\n".join(line.text for line in lines),
        "explanation": "",
        "concerns": concerns,
        "metadata": metadata,
    }


def index_from_lines(
    lines: list[Line], chapter: str, previous: list[dict], elements=None
) -> dict:
    elements = elements or []
    anchors = []
    for line in lines:
        match = NUMBER.match(line.text) or BRACKET_NUMBER.match(line.text)
        if match and not line.text.lstrip().startswith(("(", "（")):
            anchors.append((line, match.group(1)))
    concerns = []
    if not anchors:
        # A continuation is associated only when the page explicitly says it is continued.
        if (
            previous
            and lines
            and re.search(r"续解|接上页|上页续|续上页", lines[0].text)
        ):
            last = previous[-1]
            return {
                "items": [
                    {
                        "number": last["number"],
                        "chapter": last.get("chapter", chapter),
                        "answer": "",
                        "explanation": "\n".join(line.text for line in lines),
                        "regions": [
                            {"box": [0, max(0, lines[0].box[1] - 0.005), 1, 1]}
                        ],
                    }
                ],
                "concerns": ["已按明确续页标记关联上一页题号，请核对"],
            }
        return {
            "items": [],
            "concerns": ["未识别出明确题号，请在原页上手动标注，未猜测答案归属"],
        }
    starts = []
    for x in sorted(line.box[0] for line, _number in anchors):
        if not starts or x - starts[-1] > 0.22:
            starts.append(x)
    boundaries = [0]
    for left_start, right_start in pairwise(starts):
        # Use the observed gutter after left-column content, rather than a
        # midpoint between numbering positions that could cut long answers.
        edges = [
            line.box[2]
            for line in lines
            if left_start - 0.05 <= line.box[0] < right_start - 0.1
            and line.box[2] < right_start
        ]
        edges += [
            element["box"][2]
            for element in elements
            if left_start - 0.05 <= element["box"][0] < right_start - 0.1
            and element["box"][2] < right_start
        ]
        edge = max(edges, default=left_start)
        boundaries.append((edge + right_start) / 2)
    boundaries.append(1)
    items = []
    for left, right in pairwise(boundaries):
        col_anchors = sorted(
            [(line, number) for line, number in anchors if left <= line.box[0] < right],
            key=lambda entry: entry[0].box[1],
        )
        column_lines = sorted(
            [line for line in lines if left <= (line.box[0] + line.box[2]) / 2 < right],
            key=lambda line: line.box[1],
        )
        current_chapter = chapter
        for i, (anchor, number) in enumerate(col_anchors):
            headings = [
                line.text
                for line in column_lines
                if line.box[3] <= anchor.box[1] and CHAPTER.match(line.text)
            ]
            if headings:
                current_chapter = headings[-1]
            top = max(0, anchor.box[1] - 0.004)
            bottom = (
                max(top + 0.002, col_anchors[i + 1][0].box[1] - 0.004)
                if i + 1 < len(col_anchors)
                else 1
            )
            own = [
                line
                for line in column_lines
                if top <= (line.box[1] + line.box[3]) / 2 < bottom
            ]
            text = "\n".join(line.text for line in own)
            text = re.sub(
                r"^\s*(?:第\s*)?\d{1,3}(?:题)?[.．、)）]\s*", "", text, count=1
            )
            parts = re.split(r"(?:【解析】|\[解析\]|解析[：:])", text, maxsplit=1)
            answer, explanation = (
                (parts[0].strip(), parts[1].strip())
                if len(parts) == 2
                else (text.strip(), "")
            )
            items.append(
                {
                    "number": number,
                    "chapter": current_chapter,
                    "answer": answer,
                    "explanation": explanation,
                    "regions": [{"box": [left, top, right, bottom]}],
                }
            )
    if len(starts) > 1:
        concerns.append("已按分栏阅读顺序建立题号索引，请核对跨栏续解")
    concerns.append("本地索引按原页题号定位；跨页未明确标出续解的部分需要手动关联")
    return {"items": items[:300], "concerns": concerns}


def index_answers(raw, chapter, previous, formula=True, text_lines=None):
    if text_lines:
        lines = [Line(item["text"], item["box"]) for item in text_lines]
        elements, concerns, metadata = [], [], {"engine": "pdf_text", "seconds": 0}
    else:
        lines, elements, concerns, metadata = read(raw, "off", formula)
    result = index_from_lines(lines, chapter, previous, elements)
    result["concerns"] = concerns + result["concerns"]
    result["metadata"] = metadata
    return result
