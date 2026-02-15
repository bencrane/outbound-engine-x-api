import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import SuperAdminContext
from src.auth.dependencies import get_current_super_admin
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


def _set_super_admin():
    async def _override():
        return SuperAdminContext(super_admin_id="sa-1", email="sa@example.com")

    app.dependency_overrides[get_current_super_admin] = _override


def _clear_overrides():
    app.dependency_overrides.clear()


def test_webhook_signature_enforced_when_secret_set(monkeypatch):
    fake_db = FakeSupabase({"webhook_events": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", "secret123")
    monkeypatch.setattr(webhooks_router.settings, "heyreach_webhook_secret", None)
    client = TestClient(app)

    response = client.post("/api/webhooks/smartlead", json={"event": "test"})
    assert response.status_code == 401
    _clear_overrides()


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
            "providers": [{"id": "prov-1", "slug": "smartlead"}],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", None)
    monkeypatch.setattr(webhooks_router.settings, "heyreach_webhook_secret", None)
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
    _clear_overrides()


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
    monkeypatch.setattr(webhooks_router.settings, "heyreach_webhook_secret", None)
    client = TestClient(app)

    payload = {"event_id": "evt-1", "event": "reply"}
    first = client.post("/api/webhooks/smartlead", json=payload)
    second = client.post("/api/webhooks/smartlead", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["detail"] == "Duplicate event ignored"
    _clear_overrides()


def test_heyreach_webhook_signature_enforced_when_secret_set(monkeypatch):
    fake_db = FakeSupabase({"webhook_events": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "heyreach_webhook_secret", "secret456")
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", None)
    client = TestClient(app)

    response = client.post("/api/webhooks/heyreach", json={"event": "test"})
    assert response.status_code == 401
    _clear_overrides()


def test_heyreach_webhook_processes_and_updates_campaign(monkeypatch):
    fake_db = FakeSupabase(
        {
            "webhook_events": [],
            "providers": [{"id": "prov-hey", "slug": "heyreach"}],
            "company_campaigns": [
                {
                    "id": "cmp-li-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-hey",
                    "external_campaign_id": "hr-123",
                    "status": "ACTIVE",
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [
                {
                    "id": "lead-li-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-li-1",
                    "external_lead_id": "lead-77",
                    "status": "pending",
                    "deleted_at": None,
                }
            ],
            "company_campaign_messages": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "heyreach_webhook_secret", None)
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", None)
    client = TestClient(app)

    payload = {
        "event": "lead_replied",
        "campaignId": "hr-123",
        "leadId": "lead-77",
        "status": "replied",
        "messageId": "msg-88",
        "message": "Thanks, interested.",
    }
    response = client.post("/api/webhooks/heyreach", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    campaigns = fake_db.tables["company_campaigns"]
    assert campaigns[0]["status"] == "ACTIVE"
    leads = fake_db.tables["company_campaign_leads"]
    assert leads[0]["status"] == "replied"
    assert len(fake_db.tables["company_campaign_messages"]) == 1
    assert fake_db.tables["company_campaign_messages"][0]["direction"] == "inbound"
    _clear_overrides()


def test_replay_webhook_event_reapplies_payload(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-hey", "slug": "heyreach"}],
            "webhook_events": [
                {
                    "id": "evt-row-1",
                    "provider_slug": "heyreach",
                    "event_key": "evt-xyz",
                    "event_type": "lead_replied",
                    "replay_count": 0,
                    "payload": {
                        "campaignId": "hr-123",
                        "leadId": "lead-77",
                        "status": "replied",
                        "messageId": "msg-99",
                        "message": "Sounds good",
                    },
                }
            ],
            "company_campaigns": [
                {
                    "id": "cmp-li-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-hey",
                    "external_campaign_id": "hr-123",
                    "status": "ACTIVE",
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [
                {
                    "id": "lead-li-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-li-1",
                    "external_lead_id": "lead-77",
                    "status": "pending",
                    "deleted_at": None,
                }
            ],
            "company_campaign_messages": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    response = client.post("/api/webhooks/replay/heyreach/evt-xyz")
    assert response.status_code == 200
    assert response.json()["status"] == "replayed"
    assert fake_db.tables["company_campaign_leads"][0]["status"] == "replied"
    assert len(fake_db.tables["company_campaign_messages"]) == 1
    assert fake_db.tables["webhook_events"][0].get("processed_at") is not None
    assert fake_db.tables["webhook_events"][0].get("status") == "replayed"
    assert fake_db.tables["webhook_events"][0].get("replay_count") == 1
    _clear_overrides()


def test_replay_webhook_event_not_found(monkeypatch):
    fake_db = FakeSupabase({"webhook_events": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    response = client.post("/api/webhooks/replay/heyreach/missing")
    assert response.status_code == 404
    _clear_overrides()


def test_list_webhook_events_with_filter_and_limit(monkeypatch):
    fake_db = FakeSupabase(
        {
            "webhook_events": [
                {
                    "id": "w1",
                    "provider_slug": "heyreach",
                    "event_key": "k1",
                    "event_type": "lead_replied",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "created_at": "2026-02-15T10:00:00+00:00",
                },
                {
                    "id": "w2",
                    "provider_slug": "heyreach",
                    "event_key": "k2",
                    "event_type": "lead_contacted",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "created_at": "2026-02-15T11:00:00+00:00",
                },
                {
                    "id": "w3",
                    "provider_slug": "smartlead",
                    "event_key": "k3",
                    "event_type": "reply",
                    "org_id": "org-2",
                    "company_id": "c-2",
                    "created_at": "2026-02-15T12:00:00+00:00",
                },
            ]
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    response = client.get("/api/webhooks/events?provider_slug=heyreach&limit=1")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["provider_slug"] == "heyreach"
    assert rows[0]["event_key"] == "k2"
    _clear_overrides()


def test_replay_webhook_events_bulk(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-hey", "slug": "heyreach"}],
            "webhook_events": [
                {
                    "id": "evt-row-1",
                    "provider_slug": "heyreach",
                    "event_key": "evt-1",
                    "event_type": "lead_replied",
                    "replay_count": 0,
                    "payload": {
                        "campaignId": "hr-123",
                        "leadId": "lead-77",
                        "status": "replied",
                        "messageId": "msg-99",
                    },
                }
            ],
            "company_campaigns": [
                {
                    "id": "cmp-li-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-hey",
                    "external_campaign_id": "hr-123",
                    "status": "ACTIVE",
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [
                {
                    "id": "lead-li-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-li-1",
                    "external_lead_id": "lead-77",
                    "status": "pending",
                    "deleted_at": None,
                }
            ],
            "company_campaign_messages": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/webhooks/replay-bulk",
        json={"provider_slug": "heyreach", "event_keys": ["evt-1", "missing"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["requested"] == 2
    assert body["replayed"] == 1
    assert body["not_found"] == 1
    assert fake_db.tables["company_campaign_leads"][0]["status"] == "replied"
    assert fake_db.tables["webhook_events"][0].get("replay_count") == 1
    _clear_overrides()


def test_replay_webhook_events_by_query(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-hey", "slug": "heyreach"}],
            "webhook_events": [
                {
                    "id": "evt-row-1",
                    "provider_slug": "heyreach",
                    "event_key": "evt-1",
                    "event_type": "lead_replied",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "replay_count": 0,
                    "created_at": "2026-02-15T10:00:00+00:00",
                    "payload": {
                        "campaignId": "hr-123",
                        "leadId": "lead-77",
                        "status": "replied",
                        "messageId": "msg-100",
                    },
                },
                {
                    "id": "evt-row-2",
                    "provider_slug": "heyreach",
                    "event_key": "evt-2",
                    "event_type": "lead_replied",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "replay_count": 0,
                    "created_at": "2026-02-15T11:00:00+00:00",
                    "payload": {
                        "campaignId": "hr-123",
                        "leadId": "lead-77",
                        "status": "replied",
                        "messageId": "msg-101",
                    },
                },
            ],
            "company_campaigns": [
                {
                    "id": "cmp-li-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-hey",
                    "external_campaign_id": "hr-123",
                    "status": "ACTIVE",
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [
                {
                    "id": "lead-li-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-li-1",
                    "external_lead_id": "lead-77",
                    "status": "pending",
                    "deleted_at": None,
                }
            ],
            "company_campaign_messages": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/webhooks/replay-query",
        json={
            "provider_slug": "heyreach",
            "event_type": "lead_replied",
            "org_id": "org-1",
            "company_id": "c-1",
            "from_ts": "2026-02-15T10:30:00+00:00",
            "limit": 10,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] == 1
    assert body["replayed"] == 1
    assert body["results"][0]["event_key"] == "evt-2"
    evt2 = next(row for row in fake_db.tables["webhook_events"] if row["event_key"] == "evt-2")
    assert evt2["replay_count"] == 1
    _clear_overrides()
