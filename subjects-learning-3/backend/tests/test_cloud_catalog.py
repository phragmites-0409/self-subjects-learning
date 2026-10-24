import pytest
from app.api.v1.questions import delete_question
from app.core.account_scope import reset_account, set_account
from app.core.errors import AppError
from app.db.models import Question
from app.modules.accounts import cloud_catalog
from app.modules.learning.models import QuestionState
from app.modules.learning.service import discard_draft


def test_snapshot_contains_short_approved_excerpt_but_no_draft_text(db, question_factory):
    approved, version = question_factory(stem="甲" * 160, answer="秘密答案")
    draft, _ = question_factory(stem="未整理的原始内容", status="draft")

    device_id, counts, items = cloud_catalog.build_snapshot(db)

    assert len(device_id) == 36
    assert counts["questions"] == 2
    assert counts["drafts"] == 1
    approved_item = next(item for item in items if item["local_id"] == approved.id)
    draft_item = next(item for item in items if item["local_id"] == draft.id)
    assert approved_item["title"] == "甲" * 80
    assert approved_item["excerpt"] == "甲" * 120
    assert approved_item["content_sha256"] == version.content_sha256
    assert "秘密答案" not in str(items)
    assert draft_item["excerpt"] == ""
    assert draft_item["title"] == "未整理题目"


@pytest.mark.asyncio
async def test_sync_retries_incomplete_upload_and_skips_unchanged(db, question_factory, monkeypatch):
    question_factory(stem="可定位的题目")
    calls = []
    remote = []

    async def request(_client, method, path, _token, *, payload=None, prefer=""):
        calls.append((method, path, payload))
        if method == "GET":
            return [] if path.startswith("learning_tombstones?") else remote
        if path.startswith("learning_inventory?") and payload and payload[0]["manifest_sha256"] != "0" * 64:
            remote[:] = [{"manifest_sha256": payload[0]["manifest_sha256"]}]
        return None

    monkeypatch.setattr(cloud_catalog, "_request", request)
    first = await cloud_catalog.sync_catalog(db, "00000000-0000-0000-0000-000000000001", "test-token")
    assert first["changed"] is True
    assert any(method == "POST" and path.startswith("learning_catalog?") for method, path, _ in calls)
    assert any(method == "DELETE" and path.startswith("learning_catalog?") for method, path, _ in calls)
    calls.clear()
    second = await cloud_catalog.sync_catalog(db, "00000000-0000-0000-0000-000000000001", "test-token")
    assert second["changed"] is False
    assert all(method == "GET" for method, _, _ in calls)


def test_remote_tombstone_deletes_local_draft(db, question_factory):
    draft, _ = question_factory(stem="待处理", status="draft")
    conflicts = cloud_catalog._apply_draft_tombstones(db, [
        {"kind": "question", "local_id": draft.id},
    ])
    assert conflicts == []
    assert db.get(Question, draft.id).status == "deleted"
    assert db.get(QuestionState, draft.id).data["draft_deleted_at"]
    assert draft.id not in {row["local_id"] for row in cloud_catalog.build_snapshot(db)[2]}


def test_superseded_tombstone_still_discards_stale_draft(db, question_factory):
    draft, _ = question_factory(status="draft")
    cloud_catalog._apply_draft_tombstones(db, [
        {"kind": "question", "local_id": draft.id,
         "superseded_at": "2026-10-25T01:00:00Z"},
    ])
    assert db.get(Question, draft.id).status == "deleted"


def test_approved_item_is_not_silently_deleted_by_draft_tombstone(db, question_factory):
    approved, _ = question_factory()
    assert cloud_catalog._apply_draft_tombstones(db, [
        {"kind": "question", "local_id": approved.id},
    ]) == [approved.id]
    assert db.get(Question, approved.id).status == "approved"


def test_local_discard_is_a_persistent_account_tombstone(db, question_factory):
    draft, _ = question_factory(status="draft")
    discard_draft(db, draft.id)
    device_id = cloud_catalog._device_id()
    rows = cloud_catalog._local_draft_tombstones(
        db, "00000000-0000-0000-0000-000000000001", device_id,
    )
    assert len(rows) == 1
    assert rows[0]["local_id"] == draft.id
    assert rows[0]["origin_device_id"] == device_id


def test_formal_question_cannot_be_removed_before_replica_verification(db, question_factory):
    approved, _ = question_factory()
    scope = set_account("00000000-0000-0000-0000-000000000001")
    try:
        with pytest.raises(AppError) as error:
            delete_question(approved.id, db)
        assert error.value.code == "REPLICA_REQUIRED"
    finally:
        reset_account(scope)
    assert db.get(Question, approved.id).status == "approved"


def test_device_identity_survives_account_switch():
    first = cloud_catalog._device_id()
    scope = set_account("00000000-0000-0000-0000-000000000002")
    try:
        assert cloud_catalog._device_id() == first
    finally:
        reset_account(scope)


@pytest.mark.asyncio
async def test_remote_delete_precedes_catalog_upload(db, question_factory, monkeypatch):
    draft, _ = question_factory(status="draft")
    calls = []

    async def request(_client, method, path, _token, *, payload=None, prefer=""):
        calls.append((method, path, payload))
        if method == "GET" and path.startswith("learning_tombstones?"):
            return [{"kind": "question", "local_id": draft.id,
                     "deleted_at": "2026-10-25T00:00:00Z"}]
        if method == "GET":
            return []
        return None

    monkeypatch.setattr(cloud_catalog, "_request", request)
    await cloud_catalog.sync_catalog(db, "00000000-0000-0000-0000-000000000001", "test-token")
    assert db.get(Question, draft.id).status == "deleted"
    uploaded = [row for method, path, payload in calls
                if method == "POST" and path.startswith("learning_catalog?")
                for row in payload]
    assert not any(row["local_id"] == draft.id for row in uploaded)


@pytest.mark.asyncio
async def test_formal_intake_is_uploaded_even_when_another_device_deleted_draft(
    db, question_factory, monkeypatch,
):
    approved, _ = question_factory(status="approved")
    calls = []

    async def request(_client, method, path, _token, *, payload=None, prefer=""):
        calls.append((method, path, payload))
        if method == "GET" and path.startswith("learning_tombstones?"):
            return [{"kind": "question", "local_id": approved.id,
                     "deleted_at": "2026-10-25T00:00:00Z", "superseded_at": None}]
        if method == "GET":
            return []
        return None

    monkeypatch.setattr(cloud_catalog, "_request", request)
    result = await cloud_catalog.sync_catalog(
        db, "00000000-0000-0000-0000-000000000001", "test-token",
    )
    uploaded = [row for method, path, payload in calls
                if method == "POST" and path.startswith("learning_catalog?")
                for row in payload]
    assert result["formal_overrides"] == [approved.id]
    assert any(row["local_id"] == approved.id and row["status"] == "approved"
               for row in uploaded)
    assert db.get(Question, approved.id).status == "approved"
