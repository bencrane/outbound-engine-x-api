from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.main import app
from src.routers import webhooks as webhooks_router


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name: str, db: "FakeSupabase"):
        self.table_name = table_name
        self.db = db
        self.operation = "select"
        self.insert_payload = None
        self.update_payload = None
        self.filters = []

    def select(self, _fields: str):
        self.operation = "select"
        return self

    def insert(self, payload: dict):
        self.operation = "insert"
        self.insert_payload = payload
        return self

    def update(self, payload: dict):
        self.operation = "update"
        self.update_payload = payload
        return self

    def eq(self, key: str, value):
        self.filters.append(("eq", key, value))
        return self

    def is_(self, key: str, value):
        self.filters.append(("is", key, value))
        return self

    def _matches(self, row: dict) -> bool:
        for kind, key, value in self.filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "is" and value == "null" and row.get(key) is not None:
                return False
        return True

    def execute(self):
        table = self.db.tables.setdefault(self.table_name, [])
        if self.operation == "insert":
            if self.table_name == "webhook_events":
                provider = self.insert_payload.get("provider_slug")
                event_key = self.insert_payload.get("event_key")
                for row in table:
                    if row.get("provider_slug") == provider and row.get("event_key") == event_key:
                        raise Exception("duplicate key value violates unique constraint")
            row = dict(self.insert_payload or {})
            row.setdefault("id", f"{self.table_name}-{len(table)+1}")
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            table.append(row)
            return FakeResponse([row])

        if self.operation == "update":
            updated = []
            for row in table:
                if self._matches(row):
                    row.update(self.update_payload or {})
                    updated.append(dict(row))
            return FakeResponse(updated)

        rows = [dict(row) for row in table if self._matches(row)]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self, tables: dict):
        self.tables = tables

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def _base_tables():
    return {
        "webhook_events": [],
        "providers": [{"id": "prov-voicedrop", "slug": "voicedrop"}],
        "company_campaigns": [],
        "company_campaign_leads": [],
        "company_campaign_messages": [],
    }


def test_voicedrop_webhook_without_path_token_returns_401(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    client = TestClient(app)
    response = client.post("/api/webhooks/voicedrop", json={"event": "delivery_status"})
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "missing_path_token"


def test_voicedrop_webhook_wrong_path_token_returns_401(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_path_token", "vd-token")
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_allowed_origins", "api.voicedrop.ai")
    client = TestClient(app)
    response = client.post(
        "/api/webhooks/voicedrop/wrong",
        json={"event": "delivery_status"},
        headers={"Origin": "https://api.voicedrop.ai"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "invalid_path_token"


def test_voicedrop_webhook_valid_path_token_persists_event(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_path_token", "vd-token")
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_allowed_origins", "api.voicedrop.ai,voicedrop.ai")
    client = TestClient(app)
    response = client.post(
        "/api/webhooks/voicedrop/vd-token",
        json={"id": "vd-evt-1", "event": "delivery_status", "campaign_id": "cmp-1"},
        headers={"Origin": "https://api.voicedrop.ai"},
    )
    assert response.status_code == 202
    assert response.json()["status"] in {"accepted", "duplicate_ignored"}
    assert len(fake_db.tables["webhook_events"]) == 1
    assert fake_db.tables["webhook_events"][0]["provider_slug"] == "voicedrop"


def test_voicedrop_webhook_duplicate_is_idempotent(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_path_token", "vd-token")
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_allowed_origins", "api.voicedrop.ai")
    client = TestClient(app)
    payload = {"id": "vd-dup-1", "event": "delivery_status"}
    first = client.post(
        "/api/webhooks/voicedrop/vd-token",
        json=payload,
        headers={"Origin": "https://api.voicedrop.ai"},
    )
    second = client.post(
        "/api/webhooks/voicedrop/vd-token",
        json=payload,
        headers={"Origin": "https://api.voicedrop.ai"},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["status"] == "duplicate_ignored"
    assert len(fake_db.tables["webhook_events"]) == 1


def test_voicedrop_webhook_disallowed_origin_rejected(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_path_token", "vd-token")
    monkeypatch.setattr(webhooks_router.settings, "voicedrop_webhook_allowed_origins", "api.voicedrop.ai")
    client = TestClient(app)
    response = client.post(
        "/api/webhooks/voicedrop/vd-token",
        json={"id": "vd-evt-2", "event": "delivery_status"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "origin_not_allowed"
