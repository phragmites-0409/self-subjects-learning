from fastapi import APIRouter

from app.api.v1 import (
    answer_bank,
    assets,
    conversations,
    device,
    intake,
    image_edit,
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
router.include_router(image_edit.router, tags=["image-edit"])
router.include_router(answer_bank.router, tags=["answer-bank"])

from app.api.v1.knowledge_contents import router as knowledge_contents_router
router.include_router(knowledge_contents_router, tags=["knowledge-contents"])

from app.api.v1.vocabulary import router as vocabulary_router
router.include_router(vocabulary_router, tags=["vocabulary"])

from app.api.v1.question_bank import router as question_bank_router
router.include_router(question_bank_router, tags=["question-bank"])
