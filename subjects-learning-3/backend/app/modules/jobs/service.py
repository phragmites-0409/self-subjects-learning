from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Job


def create_job(db: Session, job_type: str, payload: dict) -> Job:
    job = Job(type=job_type, status="running", progress=5, payload=payload, started_at=datetime.now(UTC))
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def finish_job(db: Session, job: Job, result: dict) -> Job:
    job.status = "completed"
    job.progress = 100
    job.result = result
    job.finished_at = datetime.now(UTC)
    db.commit()
    return job


def fail_job(db: Session, job: Job, code: str) -> Job:
    job.status = "failed"
    job.error_code = code
    job.finished_at = datetime.now(UTC)
    db.commit()
    return job
