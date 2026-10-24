from hashlib import sha256
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.accounts import auth


def enable_auth(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_publishable_key", "public-test-key")


def test_registered_accounts_have_separate_questions_and_original_files(client, monkeypatch, png_bytes):
    legacy = client.post("/api/v1/learning/intake", json={"text": "原 -3 的本地题目"}).json()
    enable_auth(monkeypatch)
    first, second = str(uuid4()), str(uuid4())
    users = {auth._auth_email("first"): first, auth._auth_email("second"): second}

    async def upstream(method, path, *, payload=None, token=""):
        if path == "settings":
            return {"mailer_autoconfirm": True}
        if path == "signup":
            return {"user": {"id": users[payload["email"]]}, "access_token": "signup-token"}
        if path == "token?grant_type=password":
            uid = users[payload["email"]]
            return {"user": {"id": uid, "user_metadata": {"username": "first" if uid == first else "second"}}, "access_token": uid,
                    "refresh_token": f"refresh-{uid}", "expires_in": 3600}
        return {}

    monkeypatch.setattr(auth, "_auth_request", upstream)
    assert client.get("/api/v1/auth/config").json() == {"enabled": True}
    assert client.get("/api/v1/learning/questions").status_code == 401
    assert client.post("/api/v1/auth/register", json={"username": "first", "password": "password123"}).json() == {"username": "first"}

    client.post("/api/v1/auth/login", json={"username": "first", "password": "password123"})
    assert client.get("/api/v1/auth/me").json() == {"id": first, "username": "first"}
    first_cookie = client.cookies.get(auth.COOKIE)
    first_upload = client.post("/api/v1/assets", files={"file": ("first.png", png_bytes, "image/png")}).json()
    digest = sha256(png_bytes).hexdigest()
    media_url = f"/media/original-images/{digest[:2]}/{digest}.png"
    assert client.get(f"/api/v1/assets/{first_upload['asset_id']}/download").status_code == 200
    assert client.get(media_url).content == png_bytes
    assert client.get("/api/v1/learning/questions?filter=draft").json()["total"] == 1
    assert client.get(f"/api/v1/learning/questions/{legacy['id']}").status_code == 404

    client.post("/api/v1/auth/login", json={"username": "second", "password": "password123"})
    second_cookie = client.cookies.get(auth.COOKIE)
    assert first_cookie != second_cookie
    assert client.get("/api/v1/learning/questions?filter=draft").json()["total"] == 0
    assert client.get(f"/api/v1/assets/{first_upload['asset_id']}/download").status_code == 404
    assert client.get(media_url).status_code == 404
    second_draft = client.post("/api/v1/learning/intake", json={"text": "第二位用户的题目"}).json()
    assert client.get(f"/api/v1/learning/questions/{first_upload['question_id']}").status_code == 404

    client.cookies.set(auth.COOKIE, first_cookie)
    assert client.get("/api/v1/learning/questions?filter=draft").json()["total"] == 1
    assert client.get(f"/api/v1/learning/questions/{second_draft['id']}").status_code == 404
    assert client.get(f"/api/v1/assets/{first_upload['asset_id']}/download").content == png_bytes
    assert client.get(media_url).content == png_bytes

    data = get_settings().data_dir
    for uid in (first, second):
        assert (data / "accounts" / uid / "db" / "subjects-learning.sqlite3").is_file()
    assert (data / "db" / "subjects-learning.sqlite3").is_file()
    assert list((data / "accounts" / first / "objects" / "original-images").rglob("*.png"))
    assert not (data / "accounts" / second / "objects" / "original-images").exists()


def test_logout_and_forged_session_cannot_read_private_data(client, monkeypatch):
    enable_auth(monkeypatch)

    async def upstream(method, path, *, payload=None, token=""):
        if path == "token?grant_type=password":
            return {"user": {"id": str(uuid4()), "user_metadata": {"username": "alice"}},
                    "access_token": "token", "refresh_token": "refresh", "expires_in": 3600}
        return {}

    monkeypatch.setattr(auth, "_auth_request", upstream)
    client.cookies.set(auth.COOKIE, "forged")
    assert client.get("/api/v1/learning/questions").status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "alice", "password": "password123"}).status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/learning/questions").status_code == 401


def test_expired_upstream_session_requires_fresh_login(client, monkeypatch):
    enable_auth(monkeypatch)

    async def upstream(method, path, *, payload=None, token=""):
        if path == "token?grant_type=password":
            return {"user": {"id": str(uuid4()), "user_metadata": {"username": "alice"}},
                    "access_token": "token", "refresh_token": "refresh", "expires_in": 0}
        if path == "token?grant_type=refresh_token":
            raise AppError("AUTH_REJECTED", "令牌失效", 401)
        return {}

    monkeypatch.setattr(auth, "_auth_request", upstream)
    assert client.post("/api/v1/auth/login", json={"username": "alice", "password": "password123"}).status_code == 200
    expired_cookie = client.cookies.get(auth.COOKIE)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert expired_cookie not in auth._sessions
    assert client.get("/api/v1/learning/questions").status_code == 401


def test_username_registration_requires_auto_confirmation(client, monkeypatch):
    enable_auth(monkeypatch)
    calls = []

    async def upstream(method, path, *, payload=None, token=""):
        calls.append(path)
        return {"mailer_autoconfirm": False}

    monkeypatch.setattr(auth, "_auth_request", upstream)
    response = client.post("/api/v1/auth/register", json={"username": "alice", "password": "password123"})
    assert response.status_code == 503
    assert calls == ["settings"]


def test_username_login_rejects_mismatched_identity(client, monkeypatch):
    enable_auth(monkeypatch)

    async def upstream(method, path, *, payload=None, token=""):
        return {"user": {"id": str(uuid4()), "user_metadata": {"username": "other"}},
                "access_token": "token", "refresh_token": "refresh", "expires_in": 3600}

    monkeypatch.setattr(auth, "_auth_request", upstream)
    response = client.post("/api/v1/auth/login", json={"username": "alice", "password": "password123"})
    assert response.status_code == 401
    assert auth.COOKIE not in client.cookies
