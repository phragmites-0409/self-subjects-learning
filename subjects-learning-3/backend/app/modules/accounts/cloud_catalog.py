"""Small cloud directory for locating and checking device-held learning data."""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import (
    Asset,
    KnowledgeContent,
    KnowledgeEdge,
    KnowledgeNode,
    Paper,
    PaperItem,
    Question,
    QuestionKnowledge,
    QuestionVersion,
)
from app.documents.content import loads_compressed
from app.modules.learning.knowledge import KnowledgeNodeContents
from app.modules.learning.models import QuestionState
from app.modules.learning.service import discard_draft
from app.modules.vocabulary.models import Word
from app.storage.local_store import LocalFilesystemContentStore
from sqlalchemy import select
from sqlalchemy.orm import Session


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()


def _short(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _file_exists(store: LocalFilesystemContentStore, key: str) -> bool:
    try:
        return store.path_for(key).is_file()
    except (OSError, ValueError):
        return False


def _parsed_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _device_id() -> str:
    # The installation owns the ID, not a copied account folder. Switching
    # accounts keeps one physical device identity while account data stays split.
    path = get_settings().data_dir / "cloud-device-id"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            with path.open("x", encoding="ascii") as output:
                output.write(str(uuid4()))
        except FileExistsError:
            pass
    try:
        return str(UUID(path.read_text(encoding="ascii").strip()))
    except (OSError, ValueError) as exc:
        raise AppError("CLOUD_DEVICE_INVALID", "本机设备标识无法读取，请检查数据目录", 500) from exc


def _item(kind: str, local_id: str, title: str, excerpt: str = "", subject: str = "",
          status: str = "", updated_at: datetime | None = None,
          content_sha256: str | None = None, parent_kind: str = "",
          parent_local_id: str = "", relations: dict | None = None,
          local_available: bool = True) -> dict:
    if not 1 <= len(str(local_id)) <= 100:
        raise AppError("CLOUD_ITEM_ID_INVALID", "本机数据标识过长，无法安全同步", 422)
    if len(parent_local_id) > 100:
        raise AppError("CLOUD_PARENT_ID_INVALID", "本机上级节点标识过长，无法安全同步", 422)
    value = {
        "kind": kind, "local_id": str(local_id), "title": _short(title, 200),
        "excerpt": _short(excerpt, 120), "subject": _short(subject, 32),
        "status": _short(status, 32), "source_updated_at": _timestamp(updated_at),
        "content_sha256": content_sha256, "parent_kind": parent_kind,
        "parent_local_id": parent_local_id, "relations": relations or {},
        "local_available": local_available,
    }
    value["metadata_sha256"] = _digest(value)
    return value


def build_snapshot(db: Session) -> tuple[str, dict, list[dict]]:
    """Read only this account's SQLite and content store; omit full content and binary data."""
    device_id = _device_id()
    store = LocalFilesystemContentStore()
    items: list[dict] = []
    counts = {"questions": 0, "drafts": 0, "papers": 0, "knowledge_entries": 0,
              "knowledge_nodes": 0, "words": 0, "assets": 0, "asset_bytes": 0}
    question_links: dict[str, list[dict]] = defaultdict(list)
    for link in db.scalars(select(QuestionKnowledge)):
        question_links[link.question_id].append({"node_id": link.node_id, "relation": link.relation})
    paper_items: dict[str, list[dict]] = defaultdict(list)
    for paper_item in db.scalars(select(PaperItem).order_by(PaperItem.position)):
        paper_items[paper_item.paper_id].append({
            "question_id": paper_item.question_id,
            "version_id": paper_item.question_version_id,
            "position": paper_item.position,
            "section": paper_item.section_name,
        })
    outgoing_edges: dict[str, list[dict]] = defaultdict(list)
    for edge in db.scalars(select(KnowledgeEdge)):
        outgoing_edges[edge.source_id].append({"target_id": edge.target_id,
                                               "relation": edge.relation})

    for question in db.scalars(select(Question).where(Question.status != "deleted")):
        counts["questions"] += 1
        if question.status == "draft":
            counts["drafts"] += 1
        version = db.get(QuestionVersion, question.current_version_id) if question.current_version_id else None
        excerpt = ""
        if question.status != "draft" and version:
            try:
                payload = loads_compressed(store.read_bytes(version.content_storage_key))
                content = payload.get("content", payload)
                excerpt = content.get("stem", "") if isinstance(content, dict) else ""
            except (OSError, ValueError, UnicodeError):
                pass
        state = db.get(QuestionState, question.id)
        title = _short(excerpt, 80) if excerpt else ("未整理题目" if question.status == "draft" else question.question_type)
        items.append(_item("question", question.id, title, excerpt,
                           question.subject, question.status, question.updated_at,
                           version.content_sha256 if version else None,
                           parent_kind="node" if state and state.topic_id else "",
                           parent_local_id=state.topic_id if state and state.topic_id else "",
                           relations={"knowledge_links": question_links[question.id],
                                      "source_asset_id": question.source_asset_id},
                           local_available=bool(version and _file_exists(store, version.content_storage_key))))

    for paper in db.scalars(select(Paper)):
        counts["papers"] += 1
        items.append(_item("paper", paper.id, paper.title, subject=paper.subject,
                           status=paper.status, updated_at=paper.updated_at,
                           relations={"items": paper_items[paper.id],
                                      "student_pdf_asset_id": paper.student_pdf_asset_id,
                                      "answer_pdf_asset_id": paper.answer_pdf_asset_id}))

    for node in db.scalars(select(KnowledgeNode).where(KnowledgeNode.status != "deleted")):
        counts["knowledge_nodes"] += 1
        items.append(_item("node", node.id, node.name, subject=node.subject,
                           status=node.status, parent_kind="node" if node.parent_id else "",
                           parent_local_id=node.parent_id or "",
                           relations={"node_kind": node.kind,
                                      "outgoing_edges": outgoing_edges[node.id]}))

    for content in db.scalars(select(KnowledgeContent)):
        counts["knowledge_entries"] += 1
        items.append(_item("knowledge", content.id, content.title,
                           status="knowledge_content", parent_kind="node",
                           parent_local_id=content.node_id,
                           content_sha256=content.content_hash,
                           local_available=_file_exists(store, content.content_storage_key)))

    for node in db.scalars(select(KnowledgeNodeContents)):
        for collection in ("note_entries", "pain_entries"):
            for entry in (node.data or {}).get(collection, []):
                if not isinstance(entry, dict) or not entry.get("id"):
                    continue
                counts["knowledge_entries"] += 1
                item_id = f"{node.node_id}:{entry['id']}"
                items.append(_item("knowledge", item_id, entry.get("title", ""),
                                   status=collection, parent_kind="node",
                                   parent_local_id=node.node_id,
                                   relations={"image_asset_ids": [image.get("id") for image in entry.get("images", []) if isinstance(image, dict)]},
                                   updated_at=_parsed_time(entry.get("updated_at")),
                                   content_sha256=hashlib.sha256(str(entry.get("body", "")).encode()).hexdigest()))

    for word in db.scalars(select(Word)):
        counts["words"] += 1
        items.append(_item("word", word.id, word.word, status=word.status,
                           updated_at=word.created_at))

    for asset in db.scalars(select(Asset).where(Asset.deleted_at.is_(None))):
        counts["assets"] += 1
        counts["asset_bytes"] += asset.byte_size
        items.append(_item("asset", asset.id, asset.kind, status=asset.mime_type,
                           content_sha256=asset.sha256, updated_at=asset.created_at,
                           local_available=_file_exists(store, asset.storage_key)))

    items.sort(key=lambda row: (row["kind"], row["local_id"]))
    return device_id, counts, items


def _local_draft_tombstones(db: Session, user_id: str, device_id: str) -> list[dict]:
    rows = db.execute(select(Question.id, QuestionState.data).join(
        QuestionState, QuestionState.question_id == Question.id,
    ).where(Question.status == "deleted"))
    return [{"user_id": user_id, "kind": "question", "local_id": qid,
             "deleted_at": data["draft_deleted_at"], "origin_device_id": device_id}
            for qid, data in rows if isinstance(data, dict) and data.get("draft_deleted_at")]


async def _remote_tombstones(client: httpx.AsyncClient, user_id: str, token: str) -> list[dict]:
    result: list[dict] = []
    for offset in range(0, 100000, 100):
        batch = await _request(client, "GET",
            f"learning_tombstones?select=kind,local_id,deleted_at,superseded_at&user_id=eq.{user_id}&order=local_id&limit=100&offset={offset}",
            token) or []
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise AppError("CLOUD_TOMBSTONES_TOO_MANY", "云端删除记录过多，请联系维护人员", 503)


def _apply_draft_tombstones(db: Session, tombstones: list[dict]) -> list[str]:
    """Delete only drafts; formal intake wins and is published on this sync."""
    formal_overrides: list[str] = []
    for tombstone in tombstones:
        if tombstone.get("kind") != "question":
            continue
        qid = tombstone["local_id"]
        question = db.get(Question, qid)
        if not question:
            continue
        if question.status not in ("draft", "deleted"):
            if not tombstone.get("superseded_at"):
                formal_overrides.append(qid)
            continue
        state = db.get(QuestionState, qid) if question.status == "deleted" else None
        if question.status == "draft" or (state and (state.data or {}).get("draft_deleted_at")):
            try:
                discard_draft(db, qid)
            except AppError as exc:
                if exc.code != "DRAFT_FILE_DELETE_FAILED":
                    raise
        # A failed file delete stays on the durable local cleanup queue.
    return formal_overrides


async def _request(client: httpx.AsyncClient, method: str, path: str, token: str,
                   *, payload=None, prefer: str = ""):
    settings = get_settings()
    headers = {"apikey": settings.supabase_publishable_key,
               "Authorization": f"Bearer {token}"}
    if prefer:
        headers["Prefer"] = prefer
    try:
        response = await client.request(method, f"{settings.supabase_url.rstrip('/')}/rest/v1/{path}",
                                        json=payload, headers=headers)
    except httpx.RequestError as exc:
        raise AppError("CLOUD_UNAVAILABLE", "云端目录暂时无法连接，稍后可重新同步", 503) from exc
    if response.is_error:
        raise AppError("CLOUD_SYNC_FAILED", "云端目录请求失败，请确认迁移已部署并稍后重试", 503)
    return response.json() if response.content else None


async def cloud_overview(user_id: str, token: str, *, kind: str = "", offset: int = 0) -> dict:
    if kind and kind not in {"question", "paper", "knowledge", "node", "asset", "word"}:
        raise AppError("INVALID_CATALOG_KIND", "云端目录类型无效", 422)
    item_filter = f"&kind=eq.{kind}" if kind else ""
    async with httpx.AsyncClient(timeout=20) as client:
        inventory = await _request(client, "GET",
            f"learning_inventory?select=device_id,counts,manifest_sha256,indexed_at&user_id=eq.{user_id}", token)
        catalog = await _request(client, "GET",
            f"learning_catalog?select=device_id,kind,local_id,title,excerpt,subject,status,parent_kind,parent_local_id,relations,local_available,source_updated_at,content_sha256,indexed_at&user_id=eq.{user_id}{item_filter}&order=source_updated_at.desc.nullslast&limit=100&offset={offset}", token)
        tombstones = await _remote_tombstones(client, user_id, token)
    return {"devices": inventory or [], "items": catalog or [], "shown_limit": 100,
            "offset": offset,
            "pending_draft_deletions": sum(not row.get("superseded_at") for row in tombstones),
            "formal_overrides": sum(bool(row.get("superseded_at")) for row in tombstones)}


async def sync_catalog(db: Session, user_id: str, token: str) -> dict:
    device_id = _device_id()
    where = f"user_id=eq.{user_id}&device_id=eq.{device_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        local_tombstones = _local_draft_tombstones(db, user_id, device_id)
        for offset in range(0, len(local_tombstones), 100):
            await _request(client, "POST", "learning_tombstones?on_conflict=user_id,kind,local_id",
                token, payload=local_tombstones[offset:offset + 100],
                prefer="resolution=ignore-duplicates,return=minimal")
        tombstones = await _remote_tombstones(client, user_id, token)
        formal_overrides = _apply_draft_tombstones(db, tombstones)
        discarded = {(row["kind"], row["local_id"]) for row in tombstones}
        _, counts, snapshot = build_snapshot(db)
        items = [row for row in snapshot if (row["kind"], row["local_id"]) not in discarded
                 or (row["kind"] == "question" and row["status"] not in ("draft", "deleted"))]
        manifest = _digest({"counts": counts, "items": [item["metadata_sha256"] for item in items]})
        current = await _request(client, "GET",
            f"learning_inventory?select=manifest_sha256&{where}", token)
        if current and current[0]["manifest_sha256"] == manifest and not formal_overrides:
            return {"changed": False, "device_id": device_id, "counts": counts,
                    "formal_overrides": formal_overrides}
        if not current:
            await _request(client, "POST", "learning_inventory?on_conflict=user_id,device_id", token,
                payload=[{"user_id": user_id, "device_id": device_id,
                          "counts": {}, "manifest_sha256": "0" * 64}],
                prefer="resolution=merge-duplicates,return=minimal")
        sync_run = str(uuid4())
        for offset in range(0, len(items), 100):
            batch = [{**item, "user_id": user_id, "device_id": device_id,
                      "sync_run": sync_run} for item in items[offset:offset + 100]]
            await _request(client, "POST",
                "learning_catalog?on_conflict=user_id,device_id,kind,local_id", token,
                payload=batch, prefer="resolution=merge-duplicates,return=minimal")
        await _request(client, "DELETE",
            f"learning_catalog?{where}&sync_run=neq.{sync_run}", token,
            prefer="return=minimal")
        await _request(client, "POST", "learning_inventory?on_conflict=user_id,device_id", token,
            payload=[{"user_id": user_id, "device_id": device_id,
                      "counts": counts, "manifest_sha256": manifest,
                      "indexed_at": datetime.now(UTC).isoformat()}],
            prefer="resolution=merge-duplicates,return=minimal")
    return {"changed": True, "device_id": device_id, "counts": counts,
            "formal_overrides": formal_overrides}
