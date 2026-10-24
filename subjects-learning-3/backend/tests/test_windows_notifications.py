"""Verify native delivery receipts and visible failures without sending test-suite toasts."""
import base64
import json
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules import notifications
from app.modules.notifications import Delivery


RECEIPT = {"accepted": True, "receipt": "notification_center", "setting": "Enabled", "tag": "test"}


def native_result(monkeypatch, body, returncode=0):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=("\ufeff" + json.dumps(body, ensure_ascii=False)).encode("utf-8"), stderr=b"")
    monkeypatch.setattr(notifications.subprocess, "run", run)
    return calls


def test_test_notification_requires_native_receipt_and_records_it(client, db, monkeypatch):
    calls = native_result(monkeypatch, RECEIPT)
    response = client.post("/api/v1/learning/notifications/test")
    assert response.status_code == 200, response.text
    assert response.json()["receipt"] == RECEIPT
    args, options = calls[0]
    payload = json.loads(base64.b64decode(args[-1]).decode("utf-8"))
    assert payload["title"] == "题研 · 测试通知" and payload["url"].endswith("/")
    assert options["timeout"] == 25 and not options.get("shell")
    row = db.scalar(select(Delivery))
    assert row.status == "sent" and row.attempts == 1
    assert row.data["native"] == RECEIPT and row.data["attempted_at"]
    history = client.get("/api/v1/learning/notifications").json()["deliveries"]
    assert history[0]["native"]["receipt"] == "notification_center"


@pytest.mark.parametrize("body", [{}, {"accepted": True}, {"accepted": False, "receipt": "notification_center"}])
def test_powershell_exit_zero_without_receipt_is_not_success(client, db, monkeypatch, body):
    native_result(monkeypatch, body)
    response = client.post("/api/v1/learning/notifications/test")
    assert response.status_code == 400
    assert "投递回执" in response.json()["error"]["message"]
    assert db.scalar(select(Delivery)).status == "failed"


@pytest.mark.parametrize("error, expected", [
    ("通知身份注册失败：拒绝访问", "通知身份注册失败：拒绝访问"),
    ("Windows notification setting: DisabledForApplication", "Windows设置中已关闭题研通知"),
])
def test_native_failures_are_readable_and_saved(client, db, monkeypatch, error, expected):
    native_result(monkeypatch, {"accepted": False, "error": error}, 1)
    response = client.post("/api/v1/learning/notifications/test")
    assert response.status_code == 400
    assert expected in response.json()["error"]["message"]
    row = db.scalar(select(Delivery))
    assert row.status == "failed" and row.data["error"] == expected
    assert row.data.get("sent_at") is None


def test_native_timeout_is_visible(client, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("powershell", 25)
    monkeypatch.setattr(notifications.subprocess, "run", timeout)
    response = client.post("/api/v1/learning/notifications/test")
    assert response.status_code == 400
    assert "超时" in response.json()["error"]["message"]


def test_automatic_reminder_uses_same_receipt_contract(client, db, monkeypatch):
    native_result(monkeypatch, RECEIPT)
    client.post("/api/v1/vocabulary/words", json={"word": "test", "senses": [{"pos": "n.", "meaning": "测试"}]})
    notifications.maintain(db, day="2026-10-24", clock="19:00")
    row = db.scalar(select(Delivery))
    assert row.status == "sent" and row.data["native"] == RECEIPT
    notifications.maintain(db, day="2026-10-24", clock="19:01")
    assert row.attempts == 1
