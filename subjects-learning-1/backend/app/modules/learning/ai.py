"""Explicit OCR / analysis / answer comparison. No synthetic demo output is persisted."""

import json
from io import BytesIO

from PIL import Image, ImageOps
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.ai.contracts import LLMRequest
from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.validator import structured_prompt, validate_output
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Asset
from app.modules.learning.service import set_setting, setting
from app.storage.local_store import LocalFilesystemContentStore


class ImageRegion(BaseModel):
    box: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_box(self):
        import math

        left, top, right, bottom = self.box
        if (
            any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.box)
            or right <= left
            or bottom <= top
        ):
            raise ValueError("Invalid normalized region")
        return self


class Recognition(BaseModel):
    stem: str
    options: list[str] = Field(default_factory=list)
    subject: str = ""
    suggested_type: str = ""
    suggested_knowledge: list[str] = Field(default_factory=list)
    has_diagram: bool = False
    concerns: list[str] = Field(default_factory=list)
    diagram_regions: list[ImageRegion] = Field(default_factory=list, max_length=20)
    handwriting_regions: list[ImageRegion] = Field(default_factory=list, max_length=100)


class Analysis(BaseModel):
    answer_draft: str = ""
    explanation: str
    concerns: list[str] = Field(default_factory=list)


class SuppliedAnswer(BaseModel):
    answer: str = ""
    explanation: str = ""
    concerns: list[str] = Field(default_factory=list)


class IndexedAnswer(SuppliedAnswer):
    number: str = Field(min_length=1, max_length=100)
    chapter: str = ""
    regions: list[ImageRegion] = Field(min_length=1, max_length=20)


class AnswerIndex(BaseModel):
    items: list[IndexedAnswer] = Field(default_factory=list, max_length=300)
    concerns: list[str] = Field(default_factory=list)


class TimeEstimate(BaseModel):
    minutes: float = Field(ge=0.5, le=600)
    reason: str


class GradedAnswer(BaseModel):
    number: int
    student_answer: str = ""
    verdict: str = "uncertain"
    explanation: str = ""


class Grading(BaseModel):
    items: list[GradedAnswer]
    concerns: list[str] = Field(default_factory=list)


def configuration(db: Session):
    values = setting(db, "ai", {})
    defaults = get_settings()
    return defaults.model_copy(
        update={
            "deepseek_api_key": values.get("key", defaults.deepseek_api_key),
            "deepseek_base_url": values.get("base_url") or defaults.deepseek_base_url,
            "deepseek_model": values.get("model") or defaults.deepseek_model,
            "deepseek_vision_model": values.get("vision_model")
            or defaults.deepseek_vision_model,
        }
    )


def public_configuration(db: Session) -> dict:
    c = configuration(db)
    return {
        "configured": bool(c.deepseek_api_key),
        "base_url": c.deepseek_base_url,
        "model": c.deepseek_model,
        "vision_model": c.deepseek_vision_model,
    }


def save_configuration(db: Session, changes: dict) -> dict:
    values = {**setting(db, "ai", {})}
    for key in ("key", "base_url", "model", "vision_model"):
        if key in changes and (changes[key] or key == "key"):
            values[key] = str(changes[key]).strip()
    if values.get("base_url") and not values["base_url"].startswith(
        ("http://", "https://")
    ):
        raise AppError("AI_CONFIG_INVALID", "AI地址必须以http或https开头")
    set_setting(db, "ai", values)
    db.commit()
    return public_configuration(db)


def image_for(db: Session, aid: str | None) -> bytes | None:
    if not aid:
        return None
    asset = db.get(Asset, aid)
    if not asset:
        raise AppError("ASSET_NOT_FOUND", "图像不存在", 404)
    # AI receives a derived orientation-correct PNG; original bytes remain immutable.
    with Image.open(
        BytesIO(LocalFilesystemContentStore().read_bytes(asset.storage_key))
    ) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        im.save(buffer, "PNG")
        return buffer.getvalue()


async def generate(
    db: Session,
    task: str,
    system: str,
    data: dict,
    schema,
    aid: str | None = None,
    extra_aids: list[str] | None = None,
):
    c = configuration(db)
    if not c.deepseek_api_key:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "尚未配置AI，原件已保存，可手动校对；设置密钥后可以重试",
            409,
        )
    request = LLMRequest(
        task=task,
        system_prompt=structured_prompt(system, schema),
        user_text=json.dumps(data, ensure_ascii=False),
        image_bytes=image_for(db, aid),
        image_media_type="image/png",
        additional_image_bytes=[image_for(db, ref) for ref in (extra_aids or [])],
        # Transcription must not spend its output budget solving the question.
        thinking=task in {"optional_analysis", "grade_printed_answers", "wrong_answer_learning"},
        max_tokens=(
            32768 if task in {"optional_analysis", "grade_printed_answers", "wrong_answer_learning"}
            else 16384 if task == "index_answer_page" else 8192
        ),
    )
    response = await DeepSeekProvider(c).generate(request)
    return validate_output(response.text, schema)


async def recognize(db: Session, aid: str, text: str):
    return await generate(
        db,
        "recognize_only",
        "你只负责整理图片中的原题，禁止解题、生成答案、添加解析或虚构遮挡的信息。"
        "不要将手写笔记当作印刷原题。完整保留数字、单位、选项及公式（使用LaTeX）。图像不能用文字替代，has_diagram标明。"
        "自动分离题干与示意图：diagram_regions给出全部示意图及标注的区域；handwriting_regions仅标出与印刷题干、公式、图形完全不重叠的独立手写笔记区域。"
        "示意图按从上到下、同排从左到右排列，图形选项的区域必须包含完整曲线、坐标轴、轴字母及下方的[A]、[B]等印刷选项编号，不得只框曲线。"
        "手写圈、叉、下划线若覆盖印刷选项编号或图形，必须保留，仅在concerns说明，绝不能将该区域列入handwriting_regions。"
        "绝不把印刷文字、示意图字母或数值当作笔记；重叠笔迹保留并在concerns说明。所有区域为{box:[left,top,right,bottom]}，以正向图像宽高归一化到0至1，完整保留标注。"
        "无法分辨之处用[待核对]并列入concerns。JSON返回stem,options,subject,suggested_type,suggested_knowledge,has_diagram,diagram_regions,handwriting_regions,concerns。",
        {"user_text": text},
        Recognition,
        aid,
    )


async def analyze(db: Session, content: dict, aid: str | None):
    output = await generate(
        db,
        "optional_analysis",
        "用户主动请求高中题目解析。使用提供的原题条件，不能补造条件。"
        "必须同时给出最终答案和完整分步解析。返回JSON answer_draft（非空最终答案，仅建议，须经人工确认）,explanation（非空完整推导）,concerns。",
        {"question": content},
        Analysis,
        aid,
    )
    if not output.answer_draft.strip() or not output.explanation.strip():
        raise AppError("AI_INCOMPLETE_ANSWER", "AI未同时给出答案和解析，请重试", 502)
    return output


async def read_answer(db: Session, aid: str):
    return await generate(
        db,
        "read_supplied_answer",
        "只转录用户提供的答案照片。该内容已由用户确认，不判对错、不求解、不补充或改写原答案。返回JSON answer（原答案文字）,explanation（原解析文字，没有则为空）,concerns（无法辨认处）。公式使用LaTeX。",
        {},
        SuppliedAnswer,
        aid,
    )


async def index_answers(db: Session, aid: str, chapter: str, previous: list[dict]):
    return await generate(
        db,
        "index_answer_page",
        "识别整页参考答案中的每一道题，只转录，不解题、不判对错。返回JSON items:[{number:完整题号字符串,chapter:章节原文,answer:答案原文,explanation:解析原文,regions:[{box:[left,top,right,bottom]}]}],concerns。坐标相对于正向整页宽高，归一化0至1。一个题的答案可跨栏，分别给出多个区域。包括答案中的公式、图形和所有解析，排除相邻题。题号重复时必须用章节区分，小题保留父题号。下一页续解可参考previous，但不得编造题号，无法定位时列入concerns。",
        {"chapter_hint": chapter, "previous": previous},
        AnswerIndex,
        aid,
    )


async def estimate_time(db: Session, content: dict, aid: str | None):
    return await generate(
        db,
        "estimate_question_time",
        "预估高中学生独立完成这道题需要的分钟数，包含审题、推导、书写，不含学习解析的时间。返回JSON minutes（0.5至600，按0.5分钟刻度）,reason（简短依据）。",
        {"question": content},
        TimeEstimate,
        aid,
    )


async def grade(db: Session, items: list[dict], aid: str):
    references = []
    payload = []
    for item in items:
        copied = dict(item)
        aids = item.get("answer_asset_ids", []) if item.get("answer_confirmed") else []
        copied["reference_image_positions"] = list(
            range(len(references) + 2, len(references) + 2 + len(aids))
        )
        references.extend(aids)
        payload.append(copied)
    if len(references) > 40:
        raise AppError(
            "TOO_MANY_REFERENCE_IMAGES", "本卷答案裁片过多，请拆分试卷或人工批改", 422
        )
    return await generate(
        db,
        "grade_printed_answers",
        "第一张图是用户作答，后续图是已确认参考答案，按照每题reference_image_positions对应图片序号读取。"
        "读取用户打印卷的手写作答，按题号与提供的冻结原题和标准答案匹配。"
        "不得自行求解或补造缺失的标准答案。允许数学等价答案，未确认标准答案、题号不清、无法辨认作答一律uncertain。"
        "对wrong结果基于给定的已确认标准答案与原题条件提供分步学习解析；解析不能更改或推测标准答案。"
        "返回JSON items:[{number,student_answer,verdict:correct|wrong|uncertain,explanation:匹配说明或错误解析}],concerns。",
        {"items": payload},
        Grading,
        aid,
        references,
    )


async def explain_wrong(
    db: Session, content: dict, answer: str, student: str, aid: str | None
):
    if not answer:
        raise AppError(
            "ANSWER_NOT_CONFIRMED",
            "本卷没有已确认答案，请先人工核对并记录解析；不能让AI补造标准答案",
            409,
        )
    return await generate(
        db,
        "wrong_answer_learning",
        "这不是重新判卷。标准答案已经确认，请使用冻结的原题、标准答案和用户作答给出分步学习解析与错误原因。"
        "不得更改答案、补造条件；不能解释时明确列出concerns。JSON返回explanation,answer_draft（空字符串）,concerns。",
        {"question": content, "confirmed_answer": answer, "student_answer": student},
        Analysis,
        aid,
    )
