from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Job
from app.db.session import get_db

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise AppError("JOB_NOT_FOUND", "任务不存在", 404)
    return {"id": job.id, "type": job.type, "status": job.status, "progress": job.progress, "result": job.result, "error_code": job.error_code}
