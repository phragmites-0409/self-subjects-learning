import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Device


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DeviceService:
    def pair(self, db: Session, name: str) -> dict:
        key = secrets.token_urlsafe(32)
        device = Device(name=name.strip() or "AI 终端", key_hash=_hash_key(key))
        db.add(device)
        db.commit()
        db.refresh(device)
        return {"device_id": device.id, "device_key": key, "scopes": device.scopes_json}

    def authenticate(self, db: Session, key: str, scope: str) -> Device:
        if not key:
            raise AppError("DEVICE_UNAUTHORIZED", "缺少设备令牌", 401)
        device = db.query(Device).filter(Device.key_hash == _hash_key(key), Device.revoked_at.is_(None)).first()
        if not device or scope not in (device.scopes_json or []):
            raise AppError("DEVICE_FORBIDDEN", "设备令牌无效或权限不足", 403)
        device.last_seen_at = datetime.now(UTC)
        db.commit()
        return device
