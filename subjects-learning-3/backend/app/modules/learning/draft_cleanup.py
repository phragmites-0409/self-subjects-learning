"""Delete files owned by an abandoned intake, preserving references elsewhere."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import JSON, select

from app.core.errors import AppError
from app.db.models import Asset, Question, QuestionVersion
from app.db.session import Base
from app.documents.content import loads_compressed
from app.documents.image_pipeline import normalize_image
from app.modules.learning.models import QuestionState
from app.storage.local_store import LocalFilesystemContentStore


def references(value, candidates):
    if isinstance(value, dict):
        return set().union(*(references(item, candidates) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(references(item, candidates) for item in value))
    if isinstance(value, str):
        return {aid for aid in candidates if aid in value}
    return set()


def version_payload(store, key):
    try:
        return loads_compressed(store.read_bytes(key))
    except (OSError, ValueError, UnicodeError) as exc:
        raise AppError(
            "ASSET_REFERENCES_UNREADABLE", "历史内容无法读取，暂时不能安全清理照片", 409
        ) from exc


def thumbnails(db, assets, store):
    """Older uploads did not record a source-to-thumbnail link; recover it by hash."""
    found = set()
    for asset in assets:
        if (
            asset.mime_type not in ("image/jpeg", "image/png", "image/webp")
            or asset.kind == "thumbnail"
        ):
            continue
        try:
            _, preview, _, _ = normalize_image(store.read_bytes(asset.storage_key))
        except (OSError, ValueError):
            continue
        digest = hashlib.sha256(preview).hexdigest()
        found.update(
            db.scalars(
                select(Asset.id).where(
                    Asset.kind == "thumbnail", Asset.sha256 == digest
                )
            )
        )
    return found


def draft_assets(db, question, state):
    store = LocalFilesystemContentStore()
    assets = {asset.id: asset for asset in db.scalars(select(Asset))}
    ids = references(state.data, assets)
    if question.source_asset_id:
        ids.add(question.source_asset_id)
    for version in db.scalars(
        select(QuestionVersion).where(QuestionVersion.question_id == question.id)
    ):
        ids.update(
            references(version_payload(store, version.content_storage_key), assets)
        )
    ids.update(thumbnails(db, [assets[aid] for aid in ids if aid in assets], store))
    return ids & assets.keys()


def referenced_elsewhere(db, qid, candidates):
    if not candidates:
        return set()
    store = LocalFilesystemContentStore()
    known_ids = set(db.scalars(select(Asset.id)))
    protected = set()
    active = select(Question.id).where(Question.id != qid, Question.status != "deleted")
    protected.update(
        db.scalars(select(Question.source_asset_id).where(Question.id.in_(active)))
    )
    for data in db.scalars(
        select(QuestionState.data).where(QuestionState.question_id.in_(active))
    ):
        protected.update(references(data, known_ids))
    for version in db.scalars(
        select(QuestionVersion).where(QuestionVersion.question_id.in_(active))
    ):
        protected.update(
            references(version_payload(store, version.content_storage_key), known_ids)
        )

    # Includes answer pages, knowledge notes, frozen papers and review snapshots.
    # These references remain significant even when their question was removed.
    excluded = {
        Asset.__tablename__,
        Question.__tablename__,
        QuestionVersion.__tablename__,
        QuestionState.__tablename__,
    }
    for table in Base.metadata.tables.values():
        if table.name in excluded:
            continue
        columns = [
            column
            for column in table.columns
            if isinstance(column.type, JSON)
            or any(key.target_fullname == "assets.id" for key in column.foreign_keys)
            or column.name == "content_storage_key"
        ]
        if not columns:
            continue
        for row in db.execute(select(*columns)):
            protected.update(references(tuple(row), known_ids))
            for column, value in zip(columns, row):
                if column.name == "content_storage_key" and value:
                    try:
                        raw = store.read_bytes(value)
                        try:
                            content = loads_compressed(raw)
                        except (OSError, ValueError, UnicodeError):
                            content = raw.decode("utf-8")
                    except (OSError, ValueError, UnicodeError) as exc:
                        raise AppError(
                            "ASSET_REFERENCES_UNREADABLE",
                            "已有内容无法读取，暂时不能安全清理照片",
                            409,
                        ) from exc
                    protected.update(references(content, known_ids))
    # Shared originals also share a generated thumbnail, even on legacy uploads.
    shared = (
        db.scalars(select(Asset).where(Asset.id.in_(protected))).all()
        if protected
        else []
    )
    protected.update(thumbnails(db, shared, store))
    return protected & candidates


def finish_cleanup(db, state):
    """A durable queue allows retry after a file lock, crash, or service restart."""
    pending = state.data.get("draft_cleanup_pending", [])
    protected = referenced_elsewhere(db, state.question_id, set(pending))
    store = LocalFilesystemContentStore()
    remaining = []
    for aid in pending:
        asset = db.get(Asset, aid, populate_existing=True)
        if not asset:
            continue
        if aid in protected:
            asset.deleted_at = None
            continue
        # Uploading the same image again revives its asset and cancels old cleanup.
        if asset.deleted_at is None:
            continue
        try:
            store.delete(asset.storage_key)
        except OSError:
            remaining.append(aid)
    state.data = {
        **state.data,
        "draft_cleanup_pending": remaining,
        "draft_media_cleaned": not remaining,
    }
    db.commit()
    return not remaining


def prepare_cleanup(db, question, state):
    candidates = draft_assets(db, question, state)
    removable = candidates - referenced_elsewhere(db, question.id, candidates)
    store = LocalFilesystemContentStore()
    for asset in db.scalars(select(Asset).where(Asset.id.in_(removable))):
        store.path_for(asset.storage_key)  # Validate all paths before committing.
        asset.deleted_at = datetime.now(UTC)
    question.status = "deleted"
    question.source_asset_id = None
    state.data = {
        "draft_deleted_at": state.data.get("draft_deleted_at")
        or datetime.now(UTC).isoformat(),
        "recognition": "cancelled",
        "draft_cleanup_pending": sorted(removable),
        "draft_media_cleaned": False,
    }
    db.commit()


def retry_pending_cleanup(db):
    from app.modules.learning.service import LOCK

    with LOCK:
        states = db.scalars(
            select(QuestionState).join(Question).where(Question.status == "deleted")
        ).all()
        for state in states:
            if state.data.get("draft_cleanup_pending"):
                finish_cleanup(db, state)
