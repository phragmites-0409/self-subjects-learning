"""Ordered photo sources and recognition merged in the same crop coordinate space."""
import re

from PIL import Image

from app.core.errors import AppError
from app.db.models import Asset
from app.modules.learning import imaging
from app.modules.learning.subject_detection import detect_subject

MAX_PAGES = 8


def assemble(db, sources):
    sizes = [(item["width"], item["height"]) for item in sources]
    width = min(1600, max(w for w, _h in sizes))
    heights = [round(h * width / w) for w, h in sizes]
    height = sum(heights) + 16 * (len(sources) - 1)
    if width * height > 32_000_000:
        raise AppError("IMAGE_TOO_LARGE", "同题图片组合过大，请裁去页边空白或减少照片", 422)
    combined = Image.new("RGB", (width, height), "white")
    pages, top = [], 0
    for item, page_height in zip(sources, heights):
        image = imaging.load_image(db, item["asset_id"])
        image = image.resize((width, page_height), Image.Resampling.LANCZOS)
        combined.paste(image, (0, top))
        pages.append({**item, "box": [0, top / height, 1, (top + page_height) / height]})
        top += page_height + 16
    aid = imaging.store_image(db, combined, "question_bundle")
    return db.get(Asset, aid), pages


def map_region(region, frame):
    def box(value):
        return [frame[0] + value[0] * (frame[2] - frame[0]), frame[1] + value[1] * (frame[3] - frame[1]),
                frame[0] + value[2] * (frame[2] - frame[0]), frame[1] + value[3] * (frame[3] - frame[1])]
    return {**region, "box": box(region["box"]), "label_box": box(region["label_box"]) if region.get("label_box") else None}


def merge_pages(outputs, pages):
    stems, options, figures, notes, concerns, inline, audit = [], [], [], [], [], [], []
    for number, (output, page) in enumerate(zip(outputs, pages), 1):
        stem = output.get("stem", "").strip()
        new_options=list(output.get('options',[]))
        audit.extend({**item,'page':number,'box':map_region(item,page['box'])['box']} for item in output.get('formula_audit',[]))
        for item in output.get('inline_regions',[]):
            key=str(len(inline)+1)
            stem=stem.replace(f"[[图块:{item['key']}]]",f"[[PAGE{number}:{key}]]")
            new_options=[option.replace(f"[[图块:{item['key']}]]",f"[[PAGE{number}:{key}]]") for option in new_options]
            inline.append({**map_region(item,page['box']),'key':key,'line_height':item.get('line_height',.025)*(page['box'][3]-page['box'][1])})
        stem=re.sub(r'\[\[PAGE\d+:(\d+)\]\]',r'[[图块:\1]]',stem)
        new_options=[re.sub(r'\[\[PAGE\d+:(\d+)\]\]',r'[[图块:\1]]',option) for option in new_options]
        # Only attach a leading fragment with clear consecutive option evidence.
        leading = output.get("metadata", {}).get("leading_text", "").strip()
        previous = re.match(r"\[([A-H])\]\s+(.+)", options[-1], re.S) if options else None
        following = re.match(r"\[([A-H])\]", new_options[0]) if new_options else None
        if previous and following and ord(following[1]) == ord(previous[1]) + 1 and leading and stem.startswith(leading) and not re.match(r"[（(]?\d+[、.)）]", leading):
            options[-1] += "\n" + leading
            stem = stem[len(leading):].strip()
        if stem:
            lines = stem.splitlines()
            old = "\n".join(stems).splitlines()
            overlap = max((count for count in range(1, min(len(old), len(lines)) + 1) if old[-count:] == lines[:count]), default=0)
            stems.extend(lines[overlap:])
        for option in new_options:
            if option not in options:
                options.append(option)
        for field, target in (("diagram_regions", figures), ("handwriting_regions", notes)):
            target.extend(map_region(region, page["box"]) for region in output.get(field, []))
        concerns.extend(f"第{number}张：{note}" for note in output.get("concerns", []) if not note.startswith("选项编号未完整识别"))
    letters = [match[1] for option in options if (match := re.match(r"\[([A-H])\]", option))]
    if len(letters) != len(set(letters)):
        concerns.append("多张照片存在同编号的不同选项，请核对是否重叠或混入其他题目；未覆盖任何选项")
    if letters:
        missing = [chr(code) for code in range(ord("A"), ord(max(letters)) + 1) if chr(code) not in letters]
        if missing:
            concerns.append(f"合并后仍缺少选项{'、'.join(missing)}，请对照原图补全")
        if len(letters) == len(options):
            options.sort(key=lambda option: option[1])
    stem = "\n".join(stems)
    if stem:
        concerns = [note for note in concerns if "未识别出完整题干" not in note]
    subject_text='\n'.join(out.get('metadata',{}).get('subject_text',out.get('stem','')) for out in outputs)
    detection = detect_subject(subject_text, options)
    concerns.append("多图已按上传顺序合并，请核对跨页续文、照片重叠及选项对应")
    metadata = {"engine": "local" if all(out.get("metadata", {}).get("engine") == "local" for out in outputs) else "api",
                "seconds": round(sum(out.get("metadata", {}).get("seconds", 0) for out in outputs), 2),
                "ink": outputs[0].get("metadata", {}).get("ink", "off"), "pages": len(pages), "subject_detection": detection}
    return {"stem": stem, "options": options, "subject": detection["subject"], "has_diagram": bool(figures),
            "diagram_regions": figures, "handwriting_regions": notes, "inline_regions":inline, "formula_audit":audit, "concerns": concerns, "metadata": metadata}


def preserve_observed_labels(merged, content, regions):
    known_options = content.get("options", [])
    if not known_options or not all(re.fullmatch(r"\[[A-H]\]", option) for option in known_options):
        return merged
    labels = [option[1] for option in known_options]
    old_labels = [region.get("label") for region in regions if region.get("label")]
    new_options = merged["options"]
    if len(labels) != len(set(labels)) or sorted(old_labels) != sorted(labels) or not merged["has_diagram"]:
        return merged
    if not new_options or not all(re.fullmatch(r"\[[A-H]\]", option) for option in new_options):
        return merged
    seen = {option[1] for option in new_options}
    if not seen < set(labels):
        return merged
    missing = sorted(set(labels) - seen)
    return {**merged, "options": known_options, "diagram_regions": regions,
            "concerns": [note for note in merged["concerns"] if not note.startswith("合并后仍缺少选项")] +
            [f"处理稿漏读{'、'.join(missing)}，沿用同版本原图已识别的选项编号和图框；请核对处理稿曲线与标注"]}


async def recognize(db, source_aid, original_aid, pages, hint, content=None, known_regions=None, exclusions=None):
    from app.modules.learning import ai
    outputs = []
    for page in pages:
        aid = page["asset_id"] if source_aid == original_aid else imaging.crop_image(db, source_aid, page["box"])
        from app.modules.learning.note_filter import within_page
        page_boxes=within_page(exclusions or [],page["box"])
        result = await ai.recognize(db, aid, "", page_boxes) if page_boxes else await ai.recognize(db, aid, "")
        outputs.append({**result.model_dump(), "metadata": result._ocr_metadata})
    merged = merge_pages(outputs, pages)
    if source_aid != original_aid and content is not None and known_regions is not None:
        source, original = db.get(Asset, source_aid), db.get(Asset, original_aid)
        if (source.width, source.height) == (original.width, original.height):
            merged = preserve_observed_labels(merged, content, known_regions)
    if not merged["stem"]:
        merged["stem"] = hint
    return ai.local_result(merged, ai.Recognition)
