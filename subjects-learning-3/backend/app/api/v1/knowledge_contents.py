"""Persistent entry and original-file API, separate from question/OCR uploads."""
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import get_settings
from app.db.models import Asset, KnowledgeNode
from app.db.session import get_db
from app.modules.learning import knowledge as kb
from app.modules.learning import service as flow
from app.storage.local_store import LocalFilesystemContentStore

router = APIRouter(prefix="/learning")


@router.get("/knowledge-backup")
def export_knowledge(db: Session = Depends(get_db)):
    import base64
    from hashlib import sha256
    nodes = []
    images = {}
    for node in db.scalars(select(KnowledgeNode).where(KnowledgeNode.status == "active")):
        data = kb.content_for(db, node).data
        if node.kind == "type":
            data = {**data, "tags": flow.topic_state(db, node.id).data.get("tags", [])}
        nodes.append({"id": node.id, "name": node.name, "subject": node.subject, "kind": node.kind, "parent_id": node.parent_id, "data": data})
        for entry in data["note_entries"]:
            for image in entry["images"]:
                asset = db.get(Asset, image["id"])
                if not asset:
                    flow.fail("原图缺失，未导出不完整备份")
                try:
                    raw = LocalFilesystemContentStore().read_bytes(asset.storage_key)
                except OSError:
                    flow.fail("原图文件缺失，请先恢复原图")
                if sha256(raw).hexdigest() != image["sha256"]:
                    flow.fail("原图校验不一致，未导出不完整备份")
                images[image["id"]] = {**image, "base64": base64.b64encode(raw).decode("ascii")}
    db.commit()
    return {"format": "subjects-learning-knowledge-1", "nodes": nodes, "tag_catalog": kb.tag_catalog(db), "images": list(images.values())}


@router.post("/knowledge-backup")
def import_knowledge(body: dict, db: Session = Depends(get_db)):
    """Merge a content backup without replacing questions, scheduling or history."""
    import base64
    import binascii
    from copy import deepcopy
    from hashlib import sha256
    from uuid import UUID
    if body.get("format") != "subjects-learning-knowledge-1" or not isinstance(body.get("nodes"), list) or len(body["nodes"]) > 1500:
        flow.fail("请选择正式网页导出的知识库备份；不会导入演示题目")
    rows, ids = body["nodes"], set()
    allowed_english = {"composition_category", "phrase", "sentence_pattern", "viewpoint", "material", "sample_excerpt"}
    for row in rows:
        if not isinstance(row, dict):
            flow.fail("节点备份格式无效")
        try:
            UUID(row["id"])
        except (ValueError, TypeError, KeyError, AttributeError):
            flow.fail("节点ID无效")
        if row["id"] in ids:
            flow.fail("节点ID重复")
        ids.add(row["id"])
        if row.get("subject") not in flow.ALL_SUBJECTS or not isinstance(row.get("name"), str) or not 1 <= len(row["name"].strip()) <= 100:
            flow.fail("节点标题或学科无效")
        allowed = {"type", "knowledge"} if row["subject"] in flow.SUBJECTS else allowed_english if row["subject"] == "英语" else {"record"}
        if row.get("kind") not in allowed:
            flow.fail("节点学科与树类别不匹配")
        old = db.get(KnowledgeNode, row["id"])
        if old and (old.subject != row["subject"] or old.kind != row["kind"] or old.parent_id != row.get("parent_id")):
            flow.fail("已有节点的树归属与备份不同，未覆盖")
    prospective = {n.id: {"id": n.id, "subject": n.subject, "kind": n.kind, "name": n.name, "parent_id": n.parent_id} for n in db.scalars(select(KnowledgeNode).where(KnowledgeNode.status == "active"))}
    prospective.update({r["id"]: r for r in rows})
    names = set()
    for row in prospective.values():
        key = (row["subject"], row["kind"], row.get("parent_id"), row["name"].strip())
        if key in names:
            flow.fail("同一分类下有重复标题，未导入")
        names.add(key)
        current, seen = row, set()
        while current.get("parent_id"):
            if current["id"] in seen or len(seen) > 40:
                flow.fail("树存在循环或超过40层")
            seen.add(current["id"])
            parent = prospective.get(current["parent_id"])
            if not parent or parent["subject"] != row["subject"] or (parent["kind"] != row["kind"] and row["subject"] != "英语"):
                flow.fail("父节点缺失或跨科跨树")
            current = parent
    supplied = body.get("images", [])
    if not isinstance(supplied, list):
        flow.fail("原图备份无效")
    image_map, pending_assets = {}, []
    for item in supplied:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in image_map:
            flow.fail("原图ID无效或重复")
        try:
            raw = base64.b64decode(item.get("base64", ""), validate=True)
        except (ValueError, TypeError, binascii.Error):
            flow.fail("原图编码损坏")
        if not raw or len(raw) != item.get("size") or sha256(raw).hexdigest() != item.get("sha256"):
            flow.fail("原图校验失败，未导入")
        try:
            with Image.open(BytesIO(raw)) as picture:
                mime = Image.MIME.get(picture.format)
                picture.verify()
        except (OSError, ValueError, SyntaxError):
            flow.fail("原图文件无法读取")
        if mime != item.get("type"):
            flow.fail("原图格式与备份不一致")
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/bmp": ".bmp", "image/tiff": ".tif", "image/avif": ".avif"}.get(mime)
        if not suffix:
            flow.fail("不支持该原图格式")
        storage_key = f"knowledge-originals/{item['sha256'][:2]}/{item['sha256']}{suffix}"
        asset = db.scalar(select(Asset).where(Asset.storage_key == storage_key))
        if not asset:
            asset = Asset(id=str(uuid4()), kind="knowledge_original", storage_key=storage_key, sha256=item["sha256"], byte_size=len(raw), mime_type=mime)
            db.add(asset)
        image_map[item["id"]] = asset.id
        pending_assets.append((raw, suffix))
    # Parents must exist before children are inserted with foreign keys enabled.
    remaining = list(rows)
    while remaining:
        progressed = False
        for row in remaining[:]:
            if row.get("parent_id") and not db.get(KnowledgeNode, row["parent_id"]):
                continue
            old = db.get(KnowledgeNode, row["id"])
            if not old:
                db.add(KnowledgeNode(id=row["id"], subject=row["subject"], kind=row["kind"], parent_id=row.get("parent_id"), name=row["name"].strip(), summary=""))
            else:
                old.name = row["name"].strip()
            db.flush()
            remaining.remove(row)
            progressed = True
        if not progressed:
            flow.fail("父节点未能建立，导入已停止")
    for raw, suffix in pending_assets:
        LocalFilesystemContentStore().put_bytes("knowledge-originals", raw, suffix)
    for row in rows:
        node = db.get(KnowledgeNode, row["id"])
        incoming = row.get("data")
        if not isinstance(incoming, dict):
            flow.fail("条目数据无效")
        content = kb.content_for(db, node)
        prior = deepcopy(content.data)
        fresh = {**prior, "note_entries": [], "pain_entries": [], "tags": kb.tags(incoming.get("tags", [])), "material_type": incoming.get("material_type", "主题分类")}
        if node.subject == "英语" and fresh["material_type"] not in kb.MATERIALS:
            flow.fail("作文素材类型无效")
        content.data = fresh
        entry_ids = set()
        for collection in ("note_entries", "pain_entries"):
            values = incoming.get(collection)
            if not isinstance(values, list) or len(values) > 500:
                flow.fail("条目列表无效")
            for value in values:
                if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"] or value["id"] in entry_ids:
                    flow.fail("条目ID无效或重复")
                entry_ids.add(value["id"])
                payload = deepcopy(value)
                for image in payload.get("images", []):
                    if not isinstance(image, dict) or image.get("id") not in image_map:
                        flow.fail("备份缺少笔记原图，未导入")
                    image["id"] = image_map[image["id"]]
                # Stored files are needed by normal entry validation. Rollback keeps DB unchanged on failure.
                result = kb.save_entry(db, node, collection, payload)
                result["id"] = value["id"]
                old = next((e for e in prior.get(collection, []) if e["id"] == value["id"]), None)
                result["revision"] = old["revision"] + 1 if old else 1
                # Reassign a fresh JSON value after changing the generated entry id.
                content.data = deepcopy(content.data)
        if node.kind == "type":
            ts = flow.topic_state(db, node.id)
            ts.data = {**ts.data, "tags": fresh["tags"]}
    catalog = body.get("tag_catalog", {})
    if not isinstance(catalog, dict):
        flow.fail("标签选项库无效")
    for kind in kb.DEFAULT_TAGS:
        kb.remember_tags(db, kind, catalog.get(kind, []))
    db.commit()
    return {"nodes": len(rows), "message": "知识节点、条目和原图已合并；题目、题史和排期保持原记录"}


def get_node(db, nid):
    node = db.get(KnowledgeNode, nid)
    if not node or node.status != "active":
        flow.fail("知识节点不存在", status=404)
    return node


@router.get("/knowledge-tags")
def catalog(db: Session = Depends(get_db)):
    return kb.tag_catalog(db)


@router.post("/knowledge/{nid}/entries/{collection}")
def add_entry(nid: str, collection: str, body: dict, db: Session = Depends(get_db)):
    entry = kb.save_entry(db, get_node(db, nid), collection, body)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        flow.fail("内容已在其他页面修改，请刷新后重试", "STALE_ENTRY", 409)
    return entry


@router.patch("/knowledge/{nid}/entries/{collection}/{eid}")
def edit_entry(nid: str, collection: str, eid: str, body: dict, db: Session = Depends(get_db)):
    entry = kb.save_entry(db, get_node(db, nid), collection, body, eid)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        flow.fail("内容已在其他页面修改，请刷新后重试", "STALE_ENTRY", 409)
    return entry


@router.post("/knowledge/{nid}/reassign")
def reassign(nid: str, body: dict, db: Session = Depends(get_db)):
    remaining = kb.reassign(db, get_node(db, nid), body.get("assignments"))
    flow.activate_topics(db, flow.today())
    db.commit()
    return {"remaining": remaining}


@router.post("/knowledge-images")
async def upload_original(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read(get_settings().max_upload_bytes + 1)
    if not raw or len(raw) > get_settings().max_upload_bytes:
        flow.fail("原图不能为空，且每张不能超过10 MB", "IMAGE_SIZE", 413)
    try:
        # Validate the container only. No OCR, EXIF transform, thumbnail or re-encoding.
        with Image.open(BytesIO(raw)) as image:
            formats = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp"), "GIF": ("image/gif", ".gif"), "BMP": ("image/bmp", ".bmp"), "TIFF": ("image/tiff", ".tif"), "AVIF": ("image/avif", ".avif")}
            if image.format not in formats:
                flow.fail("不支持该图片格式")
            mime, suffix = formats[image.format]
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        flow.fail("图片文件无法读取，未保存", "INVALID_IMAGE", 422)
    key, digest = LocalFilesystemContentStore().put_bytes("knowledge-originals", raw, suffix)
    asset = db.scalar(select(Asset).where(Asset.storage_key == key))
    if not asset:
        asset = Asset(id=str(uuid4()), kind="knowledge_original", storage_key=key, sha256=digest, mime_type=mime, byte_size=len(raw))
        db.add(asset)
    db.commit()
    name = Path((file.filename or "原图").replace("\\", "/")).name[:255]
    return {"id": asset.id, "name": name, "size": len(raw), "type": mime, "sha256": digest}


@router.get("/knowledge-images/{aid}")
def original(aid: str, name: str = "", download: bool = False, db: Session = Depends(get_db)):
    asset = db.get(Asset, aid)
    if not asset or asset.kind != "knowledge_original" or asset.deleted_at:
        flow.fail("笔记原图不存在", status=404)
    path = LocalFilesystemContentStore().path_for(asset.storage_key)
    if not path.is_file():
        flow.fail("原图文件缺失，请从备份恢复", status=404)
    filename = Path(name.replace("\\", "/")).name[:255] if name else path.name
    return FileResponse(path, media_type=asset.mime_type, filename=filename, content_disposition_type="attachment" if download else "inline", headers={"X-Content-Type-Options": "nosniff"})
