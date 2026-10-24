from unittest.mock import AsyncMock

import pytest
from app.api.v1.learning import recognize_background
from app.db.models import Asset, KnowledgeNode, Paper, Question, QuestionVersion
from app.db.session import SessionLocal
from app.documents.content import dumps_compressed
from app.modules.learning import ai, imaging
from app.modules.learning.draft_cleanup import retry_pending_cleanup
from app.modules.learning.knowledge import KnowledgeNodeContents
from app.modules.learning.models import AnswerDocument, QuestionState
from app.modules.learning.service import discard_draft
from app.modules.papers.revisions import PaperRevision
from app.storage.local_store import LocalFilesystemContentStore
from sqlalchemy import select


def test_unfinished_text_draft_can_be_deleted_and_retry_is_idempotent(client, db):
    draft = client.post(
        "/api/v1/learning/intake", json={"text": "尚未整理的题目", "subject": "数学"}
    ).json()
    qid = draft["id"]
    assert client.get("/api/v1/learning/questions?filter=draft").json()["total"] == 1
    version_id = draft["version_id"]

    response = client.delete(f"/api/v1/learning/questions/{qid}/draft")

    assert response.status_code == 200
    assert response.json() == {"id": qid, "deleted": True}
    assert client.get("/api/v1/learning/questions?filter=draft").json()["total"] == 0
    assert client.get(f"/api/v1/learning/questions/{qid}").status_code == 404
    assert client.get(f"/api/v1/questions/{qid}").status_code == 404
    assert client.delete(f"/api/v1/learning/questions/{qid}/draft").status_code == 200
    db.expire_all()
    assert db.get(Question, qid).status == "deleted"
    assert db.get(QuestionState, qid).data["recognition"] == "cancelled"
    assert db.get(QuestionVersion, version_id) is not None


def test_photo_draft_before_intake_can_be_deleted_without_losing_shared_original(
    client, db, png_bytes
):
    first = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    second = client.post(
        "/api/v1/assets", files={"file": ("same.png", png_bytes, "image/png")}
    ).json()
    assert first["asset_id"] == second["asset_id"]

    assert (
        client.delete(
            f"/api/v1/learning/questions/{first['question_id']}/draft"
        ).status_code
        == 200
    )

    assert (
        client.get(f"/api/v1/assets/{first['asset_id']}/download").content == png_bytes
    )
    assert (
        client.get(f"/api/v1/learning/questions/{second['question_id']}").status_code
        == 200
    )
    db.expire_all()
    assert db.get(Question, second["question_id"]).status == "draft"
    for aid in (first["asset_id"], first["thumbnail_asset_id"]):
        assert client.get(f"/api/v1/assets/{aid}/download").status_code == 200

    # The last remaining draft releases both the shared original and thumbnail.
    assert (
        client.delete(
            f"/api/v1/learning/questions/{second['question_id']}/draft"
        ).status_code
        == 200
    )
    assert_removed(client, db, {first["asset_id"], first["thumbnail_asset_id"]})


def assert_removed(client, db, ids):
    db.expire_all()
    for aid in ids:
        asset = db.get(Asset, aid)
        assert asset.deleted_at is not None
        assert not LocalFilesystemContentStore().path_for(asset.storage_key).exists()
        assert client.get(f"/api/v1/assets/{aid}/download").status_code == 404


@pytest.mark.parametrize("legacy", [False, True])
def test_unique_photo_and_thumbnail_are_physically_deleted(
    client, db, png_bytes, legacy
):
    upload = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    if legacy:
        state = db.get(QuestionState, upload["question_id"])
        state.data = {}  # Old uploads did not persist the thumbnail link.
        db.commit()

    assert (
        client.delete(
            f"/api/v1/learning/questions/{upload['question_id']}/draft"
        ).status_code
        == 200
    )

    assert_removed(client, db, {upload["asset_id"], upload["thumbnail_asset_id"]})
    db.expire_all()
    assert db.get(Question, upload["question_id"]).source_asset_id is None
    assert db.get(QuestionState, upload["question_id"]).data["draft_media_cleaned"]


def test_multiple_originals_bundle_nested_images_and_version_images_are_deleted(
    client, db, png_bytes
):
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (40, 60), "orange").save(output, "PNG")
    draft = client.post(
        "/api/v1/learning/intake/photos",
        files=[
            ("files", ("first.png", png_bytes, "image/png")),
            ("files", ("second.png", output.getvalue(), "image/png")),
        ],
    ).json()
    q = db.get(Question, draft["question_id"])
    state = db.get(QuestionState, q.id)
    state.data = {
        **state.data,
        "image_repair_draft": {
            "mask_asset_id": imaging.store_image(db, Image.new("RGB", (9, 9), "black"))
        },
    }
    historical_image = imaging.store_image(db, Image.new("RGB", (10, 10), "blue"))
    key, digest = LocalFilesystemContentStore().put_bytes(
        "structured-content",
        dumps_compressed(
            {
                "content": {"inline_images": [{"asset_id": historical_image}]},
            }
        ),
        ".json.gz",
    )
    version = db.get(QuestionVersion, q.current_version_id)
    version.content_storage_key, version.content_sha256 = key, digest
    db.commit()
    ids = set(db.scalars(select(Asset.id)))
    assert (
        len(ids) >= 7
    )  # Two originals, two thumbnails, bundle, mask, historical image.

    assert client.delete(f"/api/v1/learning/questions/{q.id}/draft").status_code == 200

    assert_removed(client, db, ids)


@pytest.mark.parametrize("reference", ["note", "answer", "paper", "question_version"])
def test_photos_used_elsewhere_are_preserved(
    client, db, png_bytes, question_factory, reference
):
    upload = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    aid = upload["asset_id"]
    if reference == "note":
        node = KnowledgeNode(name="共享笔记", subject="数学", kind="knowledge")
        db.add(node)
        db.flush()
        db.add(
            KnowledgeNodeContents(
                node_id=node.id,
                data={"note_entries": [{"images": [{"asset_id": aid}]}]},
            )
        )
    elif reference == "answer":
        db.add(AnswerDocument(book="共享答案", filename="q.png", source_asset_id=aid))
    elif reference == "paper":
        paper = Paper(title="共享试卷", subject="数学")
        db.add(paper)
        db.flush()
        db.add(
            PaperRevision(
                paper_id=paper.id,
                number=1,
                data={"items": [{"data": {"source_asset_id": aid}}]},
            )
        )
    else:
        _, version = question_factory()
        key, digest = LocalFilesystemContentStore().put_bytes(
            "structured-content",
            dumps_compressed(
                {
                    "content": {"inline_images": [{"asset_id": aid}]},
                }
            ),
            ".json.gz",
        )
        version.content_storage_key, version.content_sha256 = key, digest
    db.commit()

    assert (
        client.delete(
            f"/api/v1/learning/questions/{upload['question_id']}/draft"
        ).status_code
        == 200
    )

    for image_id in (aid, upload["thumbnail_asset_id"]):
        assert client.get(f"/api/v1/assets/{image_id}/download").status_code == 200


def test_reuploading_deleted_photo_restores_asset_and_can_be_deleted_again(
    client, db, png_bytes
):
    first = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    client.delete(f"/api/v1/learning/questions/{first['question_id']}/draft")
    second = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()

    assert first["asset_id"] == second["asset_id"]
    assert first["question_id"] != second["question_id"]
    assert (
        client.get(f"/api/v1/assets/{second['asset_id']}/download").content == png_bytes
    )
    assert (
        client.get(
            f"/api/v1/assets/{second['thumbnail_asset_id']}/download"
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/learning/questions/{second['question_id']}/draft"
        ).status_code
        == 200
    )
    assert_removed(client, db, {second["asset_id"], second["thumbnail_asset_id"]})


def test_thumbnail_shared_by_distinct_asset_records_is_preserved(
    client, db, png_bytes, question_factory
):
    upload = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    shared = imaging.store_asset(db, png_bytes, "image/png", "processed", 80, 40)
    other, _ = question_factory()
    db.add(QuestionState(question_id=other.id, data={"processed_asset_id": shared.id}))
    db.commit()

    assert (
        client.delete(
            f"/api/v1/learning/questions/{upload['question_id']}/draft"
        ).status_code
        == 200
    )

    assert_removed(client, db, {upload["asset_id"]})
    assert client.get(f"/api/v1/assets/{shared.id}/download").content == png_bytes
    assert (
        client.get(
            f"/api/v1/assets/{upload['thumbnail_asset_id']}/download"
        ).status_code
        == 200
    )


@pytest.mark.parametrize("reupload", [False, True])
def test_locked_photo_cleanup_is_persisted_and_retried_without_harming_reupload(
    client, db, png_bytes, monkeypatch, reupload
):
    upload = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    delete = LocalFilesystemContentStore.delete

    def locked(*args):
        raise PermissionError("photo is locked")

    monkeypatch.setattr(LocalFilesystemContentStore, "delete", locked)

    response = client.delete(
        f"/api/v1/learning/questions/{upload['question_id']}/draft"
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DRAFT_FILE_DELETE_FAILED"
    db.expire_all()
    assert db.get(QuestionState, upload["question_id"]).data["draft_cleanup_pending"]
    assert (
        client.get(f"/api/v1/learning/questions/{upload['question_id']}").status_code
        == 404
    )
    if reupload:
        new = client.post(
            "/api/v1/assets", files={"file": ("same.png", png_bytes, "image/png")}
        ).json()
    monkeypatch.setattr(LocalFilesystemContentStore, "delete", delete)

    retry_pending_cleanup(db)

    db.expire_all()
    assert db.get(QuestionState, upload["question_id"]).data["draft_media_cleaned"]
    if reupload:
        assert (
            client.get(f"/api/v1/assets/{new['asset_id']}/download").content
            == png_bytes
        )
        assert (
            client.get(
                f"/api/v1/assets/{new['thumbnail_asset_id']}/download"
            ).status_code
            == 200
        )
    else:
        assert_removed(client, db, {upload["asset_id"], upload["thumbnail_asset_id"]})
    assert (
        client.delete(
            f"/api/v1/learning/questions/{upload['question_id']}/draft"
        ).status_code
        == 200
    )


def test_draft_delete_cannot_remove_a_question_already_archived(
    client, db, question_factory
):
    question, version = question_factory()

    response = client.delete(f"/api/v1/learning/questions/{question.id}/draft")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DRAFT_ALREADY_ARCHIVED"
    db.refresh(question)
    assert question.status == "approved"
    assert question.current_version_id == version.id


def test_deleting_missing_draft_returns_not_found(client):
    assert client.delete("/api/v1/learning/questions/missing/draft").status_code == 404


@pytest.mark.asyncio
async def test_a_queued_job_does_not_start_for_deleted_draft(client, monkeypatch):
    draft = client.post(
        "/api/v1/learning/intake", json={"text": "不再需要的草稿"}
    ).json()
    client.delete(f"/api/v1/learning/questions/{draft['id']}/draft")
    recognize = AsyncMock()
    monkeypatch.setattr(ai, "recognize", recognize)

    await recognize_background(draft["id"])

    recognize.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("recognition_fails", [False, True])
async def test_deletion_during_recognition_stays_deleted(
    client, db, monkeypatch, recognition_fails
):
    draft = client.post(
        "/api/v1/learning/intake", json={"text": "识别中的草稿", "subject": "数学"}
    ).json()
    qid, version = draft["id"], draft["version_id"]

    async def recognize(*args, **kwargs):
        with SessionLocal() as concurrent:
            discard_draft(concurrent, qid)
        if recognition_fails:
            raise RuntimeError("识别稍后失败")
        return ai.Recognition(stem="过期识别结果")

    monkeypatch.setattr(ai, "recognize", recognize)
    monkeypatch.setattr(
        imaging,
        "process_question",
        lambda *args, **kwargs: pytest.fail("Deleted drafts must not be processed"),
    )

    await recognize_background(qid)

    db.expire_all()
    question = db.get(Question, qid)
    assert question.status == "deleted"
    assert question.current_version_id == version
    assert db.get(QuestionState, qid).data["recognition"] == "cancelled"
    assert client.get("/api/v1/learning/questions?filter=draft").json()["total"] == 0
