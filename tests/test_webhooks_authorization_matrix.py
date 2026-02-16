from fastapi.testclient import TestClient

from src.main import app


def test_webhook_events_list_requires_super_admin_token():
    client = TestClient(app)
    response = client.get("/api/webhooks/events")
    assert response.status_code == 401


def test_webhook_replay_single_requires_super_admin_token():
    client = TestClient(app)
    response = client.post("/api/webhooks/replay/smartlead/evt-1")
    assert response.status_code == 401


def test_webhook_replay_bulk_requires_super_admin_token():
    client = TestClient(app)
    response = client.post(
        "/api/webhooks/replay-bulk",
        json={"provider_slug": "smartlead", "event_keys": ["evt-1"]},
    )
    assert response.status_code == 401


def test_webhook_replay_query_requires_super_admin_token():
    client = TestClient(app)
    response = client.post(
        "/api/webhooks/replay-query",
        json={"provider_slug": "smartlead", "limit": 10},
    )
    assert response.status_code == 401


def test_webhook_dead_letter_endpoints_require_super_admin_token():
    client = TestClient(app)
    assert client.get("/api/webhooks/dead-letters").status_code == 401
    assert client.get("/api/webhooks/dead-letters/lob:evt-1").status_code == 401
    assert client.post("/api/webhooks/dead-letters/replay", json={"event_keys": ["lob:evt-1"]}).status_code == 401
