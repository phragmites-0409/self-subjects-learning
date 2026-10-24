from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Generator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

# Settings and the SQLAlchemy engine are created at import time, so isolate them
# before importing any application modules.
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="subjects-learning-tests-"))
os.environ["APP_ENV"] = "test"
os.environ["DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["SUBJECTS_LEARNING_RUNTIME"] = str(_TEST_DATA_DIR / "runtime")
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_PUBLISHABLE_KEY"] = ""

from app.core.config import get_settings
from app.db.models import Question, QuestionVersion
from app.db.session import Base, SessionLocal, engine
from app.documents.content import dumps_compressed
from app.main import app
from app.storage.local_store import LocalFilesystemContentStore


@pytest.fixture(scope="session", autouse=True)
def remove_test_data_after_session() -> Generator[None, None, None]:
    yield
    engine.dispose()
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_backend_state() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    for name in ("objects", "tmp", "logs", "backups"):
        shutil.rmtree(settings.data_dir / name, ignore_errors=True)
    settings.ensure_data_dirs()
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def png_bytes() -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (80, 40))
    for x in range(80):
        for y in range(40):
            image.putpixel((x, y), ((x * 3) % 256, (y * 7) % 256, (x + y * 2) % 256))
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def question_factory(db) -> Callable[..., tuple[Question, QuestionVersion]]:
    def create_question(
        *,
        stem: str = "Solve x + 1 = 2.",
        answer: str = "x = 1",
        subject: str = "数学",
        question_type: str = "解答题",
        methods: list[str] | None = None,
        knowledge_points: list[str] | None = None,
        status: str = "approved",
    ) -> tuple[Question, QuestionVersion]:
        method_values = methods if methods is not None else ["代入法"]
        knowledge_values = knowledge_points if knowledge_points is not None else ["方程"]
        question = Question(
            status=status,
            subject=subject,
            grade="高中",
            question_type=question_type,
            difficulty="简单",
            methods_json=method_values,
            knowledge_points_json=knowledge_values,
        )
        db.add(question)
        db.flush()
        payload = {
            "content": {
                "schema_version": "question-content-v1",
                "subject": subject,
                "grade": "高中",
                "question_type": question_type,
                "stem": stem,
                "options": [],
                "answer": answer,
                "methods": method_values,
                "knowledge_points": knowledge_values,
                "difficulty": "简单",
                "solution_steps": [
                    {"index": 1, "title": "Solve", "content": answer, "rationale": "Direct calculation"}
                ],
            },
            "preflight": {"decision": "ready"},
            "review": {"status": "pass"},
        }
        store = LocalFilesystemContentStore()
        storage_key, digest = store.put_bytes(
            "structured-content", dumps_compressed(payload), ".json.gz"
        )
        version = QuestionVersion(
            question_id=question.id,
            version_number=1,
            content_storage_key=storage_key,
            content_sha256=digest,
            source="ai",
            validation_status="valid",
            review_status="pass",
        )
        db.add(version)
        db.flush()
        question.current_version_id = version.id
        db.commit()
        return question, version

    return create_question
