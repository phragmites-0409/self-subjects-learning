"""Build isolated UI acceptance data. Never point this at the production data directory."""
from pathlib import Path
from app.core.config import get_settings

settings = get_settings()
expected = Path(__file__).resolve().parents[1] / "data" / "tmp" / "today-preview"
if settings.data_dir != expected.resolve() or settings.app_env != "test":
    raise SystemExit("Preview data directory and test environment required")
settings.ensure_data_dirs()

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.modules.learning import service as flow

with TestClient(app) as client:
    def request(method, path, body=None):
        r = client.request(method, "/api/v1" + path, json=body)
        r.raise_for_status()
        return r.json()
    nodes = {s: request("POST", "/learning/knowledge", {"subject": s, "kind": "type", "name": s + "示例题型"})["id"] for s in flow.SUBJECTS}
    def question(subject, title, is_error=True):
        q = request("POST", "/learning/intake", {"subject": subject, "text": title, "is_error": is_error, "day": flow.today(), "context": {"from": "plan", "day": flow.today()}})
        request("PATCH", f"/learning/questions/{q['id']}", {"topic_id": nodes[subject], "answer": "示例答案"})
        return request("POST", f"/learning/questions/{q['id']}/archive")["id"]
    for subject, count in [("数学", 9), ("物理", 2), ("化学", 1), ("生物", 1)]:
        for n in range(count):
            question(subject, f"{subject}待改错示例 {n+1}：分析题目条件，写出关键步骤并核对结果。")
    for n in range(10):
        request("POST", "/learning/events", {"title": f"学习事项 {n+1}：整理课堂笔记", "day": flow.today(), "notes": "检查关键概念与易错点"})
    for n in range(7):
        qid = question("数学", f"今日过关示例 {n+1}：求解方程并检验。", False)
        with SessionLocal() as db:
            flow.mark_error(db, qid, flow.plus(flow.today(), -n), f"preview:{n}", target=flow.today())
            db.commit()
    request("POST", "/vocabulary/words", {"word": "example", "senses": [{"pos": "n.", "meaning": "例子"}]})
    request("POST", "/vocabulary/sessions/today")
    request("POST", "/learning/plan")
print("Isolated today-preview data ready")
