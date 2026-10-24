from __future__ import annotations

from app.core.config import get_settings
from app.db.models import Asset, Job, Question, QuestionVersion
from app.documents.content import loads_compressed
from app.storage.local_store import LocalFilesystemContentStore


def upload_png(client, png_bytes: bytes, *, text: str = "x + 1 = 2"):
    return client.post(
        "/api/v1/assets",
        files={"file": ("question.png", png_bytes, "image/png")},
        data={"text": text},
    )


def test_upload_rejects_unsupported_mime_type(client):
    response = client.post(
        "/api/v1/assets",
        files={"file": ("question.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_IMAGE"


def test_upload_rejects_payload_over_configured_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 8)

    response = client.post(
        "/api/v1/assets",
        files={"file": ("question.png", b"123456789", "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_upload_rejects_invalid_image_bytes(client):
    response = client.post(
        "/api/v1/assets",
        files={"file": ("question.png", b"not an image", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IMAGE"


def test_upload_preserves_original_and_deduplicates_assets_but_creates_questions(client, db, png_bytes):
    first = upload_png(client, png_bytes)
    second = upload_png(client, png_bytes)

    assert first.status_code == second.status_code == 200
    first_body, second_body = first.json(), second.json()
    assert first_body["asset_id"] == second_body["asset_id"]
    assert first_body["thumbnail_asset_id"] == second_body["thumbnail_asset_id"]
    assert first_body["question_id"] != second_body["question_id"]
    assert (first_body["width"], first_body["height"]) == (80, 40)
    db.expire_all()
    assert db.query(Asset).count() == 2
    assert db.query(Question).count() == 2
    source = db.get(Asset, first_body["asset_id"])
    assert source.mime_type == "image/png"
    assert LocalFilesystemContentStore().path_for(source.storage_key).read_bytes() == png_bytes


def test_unconfigured_ai_cannot_persist_demo_parse(client, db, png_bytes):
    question_id = upload_png(client, png_bytes).json()["question_id"]

    response = client.post(f"/api/v1/questions/{question_id}/parse", json={"text": "x + 1 = 2"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    db.expire_all()
    question = db.get(Question, question_id)
    assert question.current_version_id is not None
    version = db.get(QuestionVersion, question.current_version_id)
    assert version.question_id == question_id
    assert len(question.versions) == 1
    assert loads_compressed(LocalFilesystemContentStore().read_bytes(version.content_storage_key))["content"]["stem"] == "x + 1 = 2"
    assert db.query(Job).one().status == "failed"


def test_question_update_creates_new_version_without_mutating_old_content(client, db, question_factory):
    question, original_version = question_factory(stem="Original stem", answer="Original answer")

    response = client.patch(
        f"/api/v1/questions/{question.id}",
        json={"difficulty": "困难", "content": {"stem": "Edited stem", "answer": "Edited answer"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version_number"] == 2
    assert body["content"]["stem"] == "Edited stem"
    assert body["difficulty"] == "困难"
    db.expire_all()
    versions = db.query(QuestionVersion).filter_by(question_id=question.id).order_by(QuestionVersion.version_number).all()
    assert [item.version_number for item in versions] == [1, 2]
    original_payload = loads_compressed(LocalFilesystemContentStore().read_bytes(original_version.content_storage_key))
    assert original_payload["content"]["stem"] == "Original stem"
    assert db.get(Question, question.id).current_version_id == versions[1].id


def test_search_filters_method_membership_and_excludes_archived_questions(client, question_factory):
    matching, _ = question_factory(methods=["代入法", "配方法"], knowledge_points=["一元二次方程"])
    other, _ = question_factory(subject="物理", question_type="选择题", methods=["受力分析"])

    method_response = client.get("/api/v1/search/questions", params={"method": "代入法"})
    text_response = client.get("/api/v1/search/questions", params={"q": "一元二次"})

    assert method_response.status_code == text_response.status_code == 200
    assert [item["id"] for item in method_response.json()["items"]] == [matching.id]
    assert [item["id"] for item in text_response.json()["items"]] == [matching.id]

    deleted = client.delete(f"/api/v1/questions/{matching.id}")
    after_delete = client.get("/api/v1/search/questions", params={"method": "代入法"})

    assert deleted.status_code == 200
    assert after_delete.json()["items"] == []
    assert client.get(f"/api/v1/questions/{matching.id}").status_code == 404
    assert client.get(f"/api/v1/questions/{other.id}").status_code == 200
