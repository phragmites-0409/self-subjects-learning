from app.main import app, frontend_dist
from fastapi.testclient import TestClient


def test_frontend_deep_link_serves_spa_index():
    if not frontend_dist.exists():
        return

    with TestClient(app) as client:
        response = client.get("/questions/example-id")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in response.text


def test_frontend_fallback_does_not_mask_unknown_api_routes():
    if not frontend_dist.exists():
        return

    with TestClient(app) as client:
        response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
