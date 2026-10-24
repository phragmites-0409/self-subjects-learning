"""Daily task reminders with persisted delivery receipts and bounded retries."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import JSON, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column
from app.core.config import get_settings
from app.db.session import Base
from app.modules.learning import service as flow
from app.modules.learning.models import LearningEvent

DEFAULTS = {"desktop_enabled": True, "time": "18:00"}


class Delivery(Base):
    __tablename__ = "notification_deliveries"
    key: Mapped[str] = mapped_column(String(180), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSON)


def preferences(db):
    return {**DEFAULTS, **flow.setting(db, "notifications", {})}


def save_preferences(db, body):
    p = {**preferences(db), **{k: v for k, v in body.items() if k in DEFAULTS}}
    if type(p["desktop_enabled"]) is not bool or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(p["time"])):
        flow.fail("请检查通知开关与HH:MM时刻")
    flow.set_setting(db, "notifications", p)
    db.commit()
    return p


def send_toast(title, message, path):
    if os.name != "nt":
        raise RuntimeError("Windows桌面通知仅适用于Windows")
    script = Path(__file__).resolve().parents[3] / "scripts" / "notify.ps1"
    payload = base64.b64encode(json.dumps({"title": title, "message": message,
        "url": f"http://127.0.0.1:{get_settings().port}{path}"}, ensure_ascii=False).encode()).decode()
    try:
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Payload", payload],
            capture_output=True, timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("等待Windows通知回执超时，请重试") from exc
    output = completed.stdout.decode("utf-8-sig", errors="replace").strip()
    try:
        result = json.loads(output)
    except (ValueError, TypeError):
        result = {}
    if completed.returncode:
        detail = result.get("error") or completed.stderr.decode("utf-8-sig", errors="replace").strip() or output
        reasons = {"DisabledForApplication": "Windows设置中已关闭题研通知", "DisabledForUser": "Windows设置中已关闭通知",
                   "DisabledByGroupPolicy": "Windows策略已禁用通知", "DisabledByManifest": "Windows未允许此应用发送通知"}
        detail = next((value for key, value in reasons.items() if key in detail), detail)
        raise RuntimeError(detail[-1500:] or "Windows通知程序执行失败，未取得投递回执")
    if result.get("accepted") is not True or result.get("receipt") != "notification_center":
        raise RuntimeError("未取得Windows通知中心的投递回执，请重试")
    return result


def deliver(db, receipt, sender=None):
    # Commit the claim before invoking Windows, including manual test attempts.
    receipt.status, receipt.attempts = "sending", (receipt.attempts or 0) + 1
    receipt.data = {**receipt.data, "attempted_at": datetime.now(UTC).isoformat()}
    db.commit()
    try:
        native = (sender or send_toast)(receipt.data["title"], receipt.data["message"], receipt.data["path"])
        receipt.status = "sent"
        receipt.data = {**receipt.data, "sent_at": datetime.now(UTC).isoformat(), "error": "", "native": native}
    except Exception as exc:
        receipt.status = "failed"
        receipt.data = {**receipt.data, "error": str(exc)}
    db.commit()
    return receipt


def send_test(db):
    receipt = Delivery(key=f"test:{datetime.now(UTC).isoformat()}:{uuid4().hex[:8]}",
        data={"path": "/", "title": "题研 · 测试通知", "message": "点击打开今日安排"})
    db.add(receipt)
    deliver(db, receipt)
    if receipt.status != "sent":
        raise RuntimeError(receipt.data["error"])
    return {"sent": True, "receipt": receipt.data["native"], "key": receipt.key}


def maintain(db, *, day=None, clock=None, sender=None):
    from app.modules.vocabulary.service import ensure_session, preferences as vocabulary_preferences
    day = day or flow.today()
    clock = clock or datetime.now(timezone(timedelta(hours=8))).strftime("%H:%M")
    with flow.LOCK:
        ensure_session(db, day, clock=clock)
        p = preferences(db)
        if not p["desktop_enabled"]:
            return
        events = db.scalars(select(LearningEvent).where(LearningEvent.status == "open", LearningEvent.day <= day)).all()
        groups = [("questions", [e for e in events if e.kind in ("error", "type", "paper")], p["time"], "/"),
                  ("vocabulary", [e for e in events if e.kind == "vocabulary"], vocabulary_preferences(db)["time"], "/vocabulary?tab=practice")]
        for category, rows, due_time, path in groups:
            if not rows or clock < due_time:
                continue
            key = f"reminder:{day}:{category}"
            receipt = db.get(Delivery, key)
            if not receipt:
                receipt = Delivery(key=key, data={"path": path, "title": "题研 · 今日学习", "message": f"你有{len(rows)}项{'单词过关' if category == 'vocabulary' else '练习与回收'}待处理", "event_ids": [e.id for e in rows]})
                db.add(receipt)
                db.flush()
            if receipt.status == "sent" or receipt.attempts >= 3:
                continue
            deliver(db, receipt, sender)


def status(db):
    return {"preferences": preferences(db), "windows": os.name == "nt",
            "deliveries": [{"key": r.key, "status": r.status, "attempts": r.attempts, **r.data} for r in db.scalars(select(Delivery).order_by(Delivery.key.desc()).limit(20))]}
