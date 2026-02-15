import hashlib
import hmac
import json
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
            row.setdefault("created_at", _ts())
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


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_webhook_signature_enforced_when_secret_set(monkeypatch):
    fake_db = FakeSupabase({"webhook_events": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", "secret123")
    client = TestClient(app)

    response = client.post("/api/webhooks/smartlead", json={"event": "test"})
    assert response.status_code == 401


def test_webhook_processes_and_updates_campaign(monkeypatch):
    fake_db = FakeSupabase(
        {
            "webhook_events": [],
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-1",
                    "external_campaign_id": "123",
                    "status": "DRAFTED",
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", None)
    client = TestClient(app)

    payload = {
        "event": "campaign_status_updated",
        "campaign_id": "123",
        "status": "ACTIVE",
        "message_id": "m-1",
        "subject": "hello",
    }
    response = client.post("/api/webhooks/smartlead", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    campaigns = fake_db.tables["company_campaigns"]
    assert campaigns[0]["status"] == "ACTIVE"
    assert len(fake_db.tables["webhook_events"]) == 1


def test_webhook_duplicate_is_ignored(monkeypatch):
    fake_db = FakeSupabase(
        {
            "webhook_events": [],
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", None)
    client = TestClient(app)

    payload = {"event_id": "evt-1", "event": "reply"}
    first = client.post("/api/webhooks/smartlead", json=payload)
    second = client.post("/api/webhooks/smartlead", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["detail"] == "Duplicate event ignored"
