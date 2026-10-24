from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.modules.learning import service as flow
from app.modules.question_bank import imports

router = APIRouter(prefix="/question-bank")


class TextImport(BaseModel):
    text: str = Field(max_length=2_000_000)


class ImportConfirmation(BaseModel):
    answers_confirmed: bool = False


@router.post("/imports/preview")
def preview(body: TextImport, db: Session = Depends(get_db)):
    with flow.LOCK:
        return imports.preview(db, body.text)


@router.post("/imports/{iid}/confirm")
def confirm(iid: str, body: ImportConfirmation, db: Session = Depends(get_db)):
    with flow.LOCK:
        return imports.confirm(db, iid, body.answers_confirmed)
