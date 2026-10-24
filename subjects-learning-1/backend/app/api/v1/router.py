from fastapi import APIRouter

from app.api.v1 import (
    answer_bank,
    assets,
    conversations,
    device,
    intake,
    jobs,
    learning,
    papers,
    questions,
    search,
    settings,
)

router = APIRouter(prefix="/api/v1")
router.include_router(assets.router, tags=["assets"])
router.include_router(questions.router, prefix="/questions", tags=["questions"])
router.include_router(conversations.router, tags=["conversations"])
router.include_router(search.router, tags=["search"])
router.include_router(papers.router, prefix="/papers", tags=["papers"])
router.include_router(jobs.router, tags=["jobs"])
router.include_router(settings.router, tags=["settings"])
router.include_router(device.router, prefix="/device", tags=["device"])
router.include_router(learning.router, tags=["learning"])
router.include_router(intake.router, tags=["intake"])
router.include_router(answer_bank.router, tags=["answer-bank"])
