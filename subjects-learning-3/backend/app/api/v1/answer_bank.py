"""Index full answer pages; crop the selected answer from immutable originals."""

from io import BytesIO

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.intake import supplied_answer
from app.api.v1.learning import question
from app.core.account_scope import schedule
from app.core.errors import AppError
from app.db.session import SessionLocal, get_db
from app.modules.learning import ai, imaging
from app.modules.learning import service as flow
from app.modules.learning.models import AnswerDocument, AnswerPage

router = APIRouter(prefix="/learning/answer-bank")


def document(db, did):
    row = db.get(AnswerDocument, did)
    if not row:
        flow.fail("答案资料不存在", status=404)
    return row


def pages(db, did):
    return db.scalars(
        select(AnswerPage)
        .where(AnswerPage.document_id == did)
        .order_by(AnswerPage.number)
    ).all()


def document_view(db, row, detail=False):
    result = {
        "id": row.id,
        "book": row.book,
        "edition": row.edition,
        "chapter": row.chapter,
        "filename": row.filename,
        "source_asset_id": row.source_asset_id,
    }
    entries = pages(db, row.id)
    result["page_count"] = len(entries)
    result["indexed_count"] = sum(len(p.data.get("items", [])) for p in entries)
    result["pending"] = any(
        p.data.get("status") in ("queued", "running") for p in entries
    )
    if detail:
        result["pages"] = [
            {"id": p.id, "number": p.number, "asset_id": p.asset_id, **p.data}
            for p in entries
        ]
    return result


async def index_document(did):
    with SessionLocal() as db:
        doc = document(db, did)
        previous = []
        for page in pages(db, did):
            if page.data.get("status") != "queued":
                previous = page.data.get("items", [])[-5:]
                continue
            revision = page.data.get("revision", 0)
            page.data = {**page.data, "status": "running"}
            db.commit()
            try:
                if page.data.get("pdf_text_lines"):
                    output = await ai.index_answers(
                        db,
                        page.asset_id,
                        doc.chapter,
                        previous,
                        text_lines=page.data["pdf_text_lines"],
                    )
                else:
                    output = await ai.index_answers(
                        db, page.asset_id, doc.chapter, previous
                    )
                db.refresh(page)
                if page.data.get("revision", 0) != revision:
                    # Manual corrections made during OCR are authoritative.
                    continue
                entries = [entry.model_dump() for entry in output.items]
                for entry in entries:
                    entry["chapter"] = entry["chapter"].strip() or doc.chapter
                page.data = {
                    **page.data,
                    "status": "completed",
                    "items": entries,
                    "note": "；".join(output.concerns),
                    "recognition_info": output._ocr_metadata,
                }
                previous = entries[-5:]
                db.commit()
            except Exception as exc:  # noqa: BLE001 - Persist detached OCR failures; originals survive.
                db.rollback()
                db.refresh(page)
                if page.data.get("revision", 0) == revision:
                    page.data = {
                        **page.data,
                        "status": "failed",
                        "note": str(exc)[:500],
                    }
                    db.commit()


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    return {
        "items": [
            document_view(db, row)
            for row in db.scalars(
                select(AnswerDocument).order_by(AnswerDocument.created_at.desc())
            )
        ]
    }


@router.post("/import")
async def import_document(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    book: str = Form(...),
    chapter: str = Form(""),
    edition: str = Form(""),
    db: Session = Depends(get_db),
):
    book, chapter, edition = book.strip(), chapter.strip(), edition.strip()
    if (
        not book
        or len(book) > 200
        or len(chapter) > 200
        or len(edition) > 100
        or not 1 <= len(files) <= 20
    ):
        flow.fail("请填写资料名，单次最多上传20个文件")
    doc = None
    count, total_bytes = 0, 0
    configured = ai.recognition_available(db)
    any_queued = False
    for file in files:
        mime = file.content_type
        if mime not in ("application/pdf", "image/jpeg", "image/png", "image/webp"):
            raise AppError("UNSUPPORTED_ANSWER_FILE", "答案库支持照片和PDF", 415)
        raw = await file.read(50 * 1024 * 1024 + 1)
        total_bytes += len(raw)
        if len(raw) > 50 * 1024 * 1024 or total_bytes > 75 * 1024 * 1024:
            raise AppError("FILE_TOO_LARGE", "单文件最多50 MB，单批合计最多75 MB", 413)
        try:
            if mime == "application/pdf":
                import fitz

                pdf = fitz.open(stream=raw, filetype="pdf")
                if pdf.needs_pass or not 1 <= len(pdf) <= 100 or len(pdf) + count > 100:
                    pdf.close()
                    flow.fail("请上传未加密PDF，单批最多100页")
                source = imaging.store_asset(db, raw, mime, "answer_source")

                def rendered_pages(pdf=pdf):
                    try:
                        for page in pdf:
                            rect = page.rect
                            scale = min(2.5, 2400 / max(rect.width, rect.height))
                            pix = page.get_pixmap(
                                matrix=fitz.Matrix(scale, scale),
                                alpha=False,
                                colorspace=fitz.csRGB,
                            )
                            text_lines = []
                            for block in page.get_text("dict").get("blocks", []):
                                for line in block.get("lines", []):
                                    text = "".join(
                                        span.get("text", "")
                                        for span in line.get("spans", [])
                                    ).strip()
                                    if not text or "�" in text:
                                        continue
                                    box = fitz.Rect(line["bbox"]) * page.rotation_matrix
                                    normalized = [
                                        max(0, box.x0 / rect.width),
                                        max(0, box.y0 / rect.height),
                                        min(1, box.x1 / rect.width),
                                        min(1, box.y1 / rect.height),
                                    ]
                                    if (
                                        normalized[2] > normalized[0]
                                        and normalized[3] > normalized[1]
                                    ):
                                        text_lines.append(
                                            {"text": text, "box": normalized}
                                        )
                            yield (
                                Image.frombytes(
                                    "RGB", (pix.width, pix.height), pix.samples
                                ),
                                text_lines[:3000],
                            )
                    finally:
                        pdf.close()

                images = rendered_pages()
            else:
                with Image.open(BytesIO(raw)) as im:
                    if im.width * im.height > 40_000_000:
                        flow.fail("照片像素过大，请缩小后上传")
                    image = ImageOps.exif_transpose(im).convert("RGB")
                source = imaging.store_asset(
                    db, raw, mime, "answer_source", *image.size
                )
                images = iter([(image, [])])
            if doc is None:
                doc = AnswerDocument(
                    book=book,
                    chapter=chapter,
                    edition=edition,
                    source_asset_id=source.id,
                    filename="、".join((f.filename or "答案") for f in files)[:255],
                )
                db.add(doc)
                db.flush()
            for image, text_lines in images:
                can_index = configured or (
                    ai.recognition_configuration(db)["mode"] == "local"
                    and bool(text_lines)
                )
                any_queued = any_queued or can_index
                count += 1
                if count > 100:
                    flow.fail("单批最多100页")
                aid = imaging.store_image(db, image, "answer_page")
                db.add(
                    AnswerPage(
                        document_id=doc.id,
                        asset_id=aid,
                        number=count,
                        data={
                            "source_asset_id": source.id,
                            "status": "queued" if can_index else "manual",
                            "items": [],
                            "pdf_text_lines": text_lines,
                            "note": ""
                            if can_index
                            else "识别未准备好；原页已保存，可手动标注或准备本地模型后识别",
                        },
                    )
                )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "INVALID_ANSWER_FILE", "无法读取答案文件，请检查照片或PDF", 422
            ) from exc
    db.commit()
    if any_queued:
        schedule(background, index_document, doc.id)
    return document_view(db, doc, True)


@router.get("/lookup")
def lookup(
    book: str,
    number: str,
    chapter: str = "",
    edition: str = "",
    db: Session = Depends(get_db),
):
    if not book.strip() or not number.strip():
        flow.fail("请填写资料名和题号")
    matches = []
    docs = db.scalars(select(AnswerDocument).where(AnswerDocument.book == book.strip()))
    for doc in docs:
        if edition and doc.edition != edition.strip():
            continue
        groups = {}
        for page in pages(db, doc.id):
            for idx, entry in enumerate(page.data.get("items", [])):
                if entry["number"].strip() != number.strip() or (
                    chapter
                    and entry.get("chapter", doc.chapter).strip() != chapter.strip()
                ):
                    continue
                key = entry.get("chapter", doc.chapter)
                groups.setdefault(key, []).append(
                    {
                        "page_id": page.id,
                        "page_number": page.number,
                        "item_index": idx,
                        "asset_id": page.asset_id,
                        **entry,
                    }
                )
        for ch, entries in groups.items():
            matches.append(
                {
                    "document_id": doc.id,
                    "book": doc.book,
                    "edition": doc.edition,
                    "chapter": ch,
                    "number": number.strip(),
                    "filename": doc.filename,
                    "entries": entries,
                }
            )
    return {"items": matches}


@router.get("/{did}")
def get_document(did: str, db: Session = Depends(get_db)):
    return document_view(db, document(db, did), True)


@router.post("/{did}/index")
def reindex(did: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    document(db, did)
    rows = pages(db, did)
    if not ai.recognition_available(db) and not (
        ai.recognition_configuration(db)["mode"] == "local"
        and any(p.data.get("pdf_text_lines") for p in rows)
    ):
        flow.fail("识别尚未准备好，请查看设置中的图片识别状态")
    if any(p.data.get("status") in ("queued", "running") for p in rows):
        flow.fail("答案页正在识别，请稍候", status=409)
    for page in rows:
        # Successful/manual indexes are never overwritten by a retry.
        if page.data.get("status") != "completed":
            if not ai.recognition_available(db) and not page.data.get("pdf_text_lines"):
                continue
            page.data = {**page.data, "status": "queued"}
    db.commit()
    schedule(background, index_document, did)
    return {"queued": True}


@router.patch("/pages/{pid}")
def edit_page(pid: str, body: dict, db: Session = Depends(get_db)):
    page = db.get(AnswerPage, pid)
    if not page:
        flow.fail("答案页不存在", status=404)
    from pydantic import ValidationError

    try:
        index = ai.AnswerIndex.model_validate(body)
    except ValidationError as exc:
        raise AppError("INVALID_ANSWER_INDEX", "请填写题号和有效裁切范围", 422) from exc
    doc = document(db, page.document_id)
    entries = [entry.model_dump() for entry in index.items]
    for entry in entries:
        entry["chapter"] = entry["chapter"].strip() or doc.chapter
    page.data = {
        **page.data,
        "items": entries,
        "status": "completed",
        "note": "",
        "revision": page.data.get("revision", 0) + 1,
    }
    db.commit()
    return document_view(db, doc, True)


@router.post("/apply/{qid}")
def apply_answer(qid: str, body: dict, db: Session = Depends(get_db)):
    flow.get_question(db, qid)
    doc = document(db, body.get("document_id"))
    number, chapter = (
        str(body.get("number", "")).strip(),
        str(body.get("chapter", "")).strip(),
    )
    crops, answers, explanations, references = [], [], [], []
    for page in pages(db, doc.id):
        for entry in page.data.get("items", []):
            if (
                entry["number"].strip() == number
                and entry.get("chapter", doc.chapter).strip() == chapter
            ):
                for region in entry["regions"]:
                    crops.append(imaging.crop_image(db, page.asset_id, region["box"]))
                    references.append(
                        {
                            "page_id": page.id,
                            "source_asset_id": page.asset_id,
                            "box": region["box"],
                        }
                    )
                if entry.get("answer"):
                    answers.append(entry["answer"])
                if entry.get("explanation"):
                    explanations.append(entry["explanation"])
    if not crops:
        flow.fail("没有匹配的答案，请重新选择资料、章节和题号", status=404)
    supplied_answer(
        db,
        qid,
        "\n".join(dict.fromkeys(answers)),
        "\n".join(explanations),
        crops,
        "bank",
        {
            "document_id": doc.id,
            "book": doc.book,
            "edition": doc.edition,
            "chapter": chapter,
            "number": number,
            "regions": references,
        },
    )
    return question(qid, db=db)
