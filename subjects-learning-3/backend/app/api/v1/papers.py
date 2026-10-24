from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.providers.deepseek import DeepSeekProvider
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Paper
from app.db.session import get_db
from app.modules.papers.schemas import PaperCreate, PaperUpdate
from app.modules.papers.service import PaperService
from app.modules.questions.service import QuestionService
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter()


def service() -> PaperService:
    settings = get_settings()
    store = LocalFilesystemContentStore()
    questions = QuestionService(store, AIGateway(DeepSeekProvider(settings), settings))
    return PaperService(store, settings, questions)


@router.get("")
def list_papers(db: Session = Depends(get_db)):
    return {"items": service().list(db)}


@router.post("")
def create_paper(request: PaperCreate, db: Session = Depends(get_db)):
    return service().create(db, request.title, request.subject, request.grade, [item.model_dump() for item in request.items])


@router.get("/{paper_id}")
def get_paper(paper_id: str, db: Session = Depends(get_db)):
    return service().get(db, paper_id)


@router.patch("/{paper_id}")
def update_paper(paper_id: str, request: PaperUpdate, db: Session = Depends(get_db)):
    paper = db.get(Paper, paper_id)
    if not paper:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
    return service().update(db, paper, request.model_dump(exclude_none=True))


@router.post("/{paper_id}/export")
def export_paper(paper_id: str, include_answers: bool = False, revision_id: str = "", db: Session = Depends(get_db)):
    paper = db.get(Paper, paper_id)
    if not paper:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
    from app.modules.papers.revisions import latest, capture, PaperRevision
    from app.modules.learning.pdf import export_pdf
    from app.db.models import Asset
    from app.modules.learning import service as flow
    with flow.LOCK:
        revision = db.get(PaperRevision, revision_id) if revision_id else latest(db, paper) or capture(db, paper)
        if not revision or revision.paper_id != paper.id:
            flow.fail("试卷版本不存在", status=404)
        key = "answers" if include_answers else "student"
        exports = revision.data.get("exports", {})
        asset = db.get(Asset, exports.get(key)) if exports.get(key) else None
        store = LocalFilesystemContentStore()
        if not asset:
            path = export_pdf(db, revision.id, include_answers, frozen=revision.data)
            data = path.read_bytes()
            storage_key, digest = store.put_bytes("generated-pdfs", data, ".pdf")
            asset = Asset(kind="generated_pdf", storage_key=storage_key, sha256=digest, mime_type="application/pdf", byte_size=len(data))
            db.add(asset)
            db.flush()
            revision.data = {**revision.data, "exports": {**exports, key: asset.id}}
        if revision.id == latest(db, paper).id:
            if include_answers:
                paper.answer_pdf_asset_id = asset.id
            else:
                paper.student_pdf_asset_id = asset.id
            paper.status = "generated"
        db.commit()
        return {"paper": service().serialize(db, paper), "asset_id": asset.id, "download_url": f"/api/v1/assets/{asset.id}/download"}


@router.get("/{paper_id}/revisions")
def revisions(paper_id: str, db: Session = Depends(get_db)):
    from app.modules.papers.revisions import view
    paper = db.get(Paper, paper_id)
    if not paper:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
    return view(db, paper)


@router.post("/{paper_id}/copy")
def copy_paper(paper_id: str, db: Session = Depends(get_db)):
    import copy
    from app.modules.papers.revisions import latest, capture
    paper = db.get(Paper, paper_id)
    if not paper:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
    revision = latest(db, paper) or capture(db, paper)
    data = revision.data
    result = service().create(db, data["title"] + "（副本）", data["subject"], paper.grade,
        [{"question_id": i["question_id"], "question_version_id": i["version_id"], "points": i["data"]["points"], "section_name": i["data"]["section_name"]} for i in data["items"]])
    frozen = latest(db, db.get(Paper, result["id"]))
    frozen.data = {**copy.deepcopy(data), "title": result["title"], "exports": {}}
    db.commit()
    return result


@router.post("/{paper_id}/schedule")
def schedule_paper(paper_id: str, body: dict, db: Session = Depends(get_db)):
    from app.modules.papers.revisions import latest, capture, schedule
    from app.modules.learning import service as flow
    from datetime import date
    paper = db.get(Paper, paper_id)
    if not paper:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在", 404)
    try:
        day = date.fromisoformat(str(body.get("day", flow.today()))).isoformat()
    except ValueError:
        flow.fail("计划日期格式不正确")
    with flow.LOCK:
        flow.sync(db)
        return schedule(db, paper, latest(db, paper) or capture(db, paper), day)
