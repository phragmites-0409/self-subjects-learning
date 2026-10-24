"""Authenticated view and explicit sync of the small cloud learning directory."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.accounts.auth import current_session
from app.modules.accounts.cloud_catalog import cloud_overview, sync_catalog

router = APIRouter(prefix="/cloud-catalog", tags=["cloud-catalog"])


@router.get("")
async def overview(request: Request, kind: str = "", offset: int = Query(default=0, ge=0)):
    session = await current_session(request)
    return await cloud_overview(session.user_id, session.access_token, kind=kind, offset=offset)


@router.post("/sync")
async def sync(request: Request, db: Session = Depends(get_db)):
    session = await current_session(request)
    return await sync_catalog(db, session.user_id, session.access_token)
