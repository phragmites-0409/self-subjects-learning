from __future__ import annotations

from datetime import UTC, datetime

from app.db.models import Device


def pair_device(client, name: str = "Study board") -> dict:
    response = client.post("/api/v1/device/pair", json={"name": name})
    assert response.status_code == 200
    return response.json()


def test_device_health_requires_token(client):
    response = client.get("/api/v1/device/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "DEVICE_UNAUTHORIZED"


def test_device_health_rejects_unknown_token(client):
    response = client.get("/api/v1/device/health", headers={"X-Device-Key": "unknown"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DEVICE_FORBIDDEN"


def test_paired_device_can_access_health_and_updates_last_seen(client, db):
    paired = pair_device(client, "  Classroom board  ")

    response = client.get("/api/v1/device/health", headers={"X-Device-Key": paired["device_key"]})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "device_id": paired["device_id"], "server": "ready"}
    db.expire_all()
    device = db.get(Device, paired["device_id"])
    assert device.name == "Classroom board"
    assert device.last_seen_at is not None


def test_device_scope_is_enforced(client, db):
    paired = pair_device(client)
    device = db.get(Device, paired["device_id"])
    device.scopes_json = ["question:read"]
    db.commit()

    response = client.post(
        "/api/v1/device/questions/missing/messages",
        headers={"X-Device-Key": paired["device_key"]},
        json={"text": "Explain this"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DEVICE_FORBIDDEN"


def test_revoked_device_key_is_rejected(client, db):
    paired = pair_device(client)
    device = db.get(Device, paired["device_id"])
    device.revoked_at = datetime.now(UTC)
    db.commit()

    response = client.get("/api/v1/device/health", headers={"X-Device-Key": paired["device_key"]})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DEVICE_FORBIDDEN"
