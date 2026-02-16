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


def _lob_signed_headers(body: str, *, secret: str, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(datetime.now(timezone.utc).timestamp()))
    signature = hmac.new(secret.encode("utf-8"), f"{ts}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "Lob-Signature": signature,
        "Lob-Signature-Timestamp": ts,
    }


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


def test_lob_replay_bulk_duplicate_keys_are_idempotent(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [
                {
                    "id": "evt-row-lob-1",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-1",
                    "event_type": "piece.in_transit",
                    "replay_count": 0,
                    "payload": {"resource_id": "psc_1", "body": {"resource": {"id": "psc_1", "object": "postcard"}}},
                }
            ],
            "company_direct_mail_pieces": [
                {
                    "id": "piece-row-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-lob",
                    "external_piece_id": "psc_1",
                    "piece_type": "postcard",
                    "status": "queued",
                    "deleted_at": None,
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_batch_size", 10)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_max_concurrent_workers", 4)
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/webhooks/replay-bulk",
        json={"provider_slug": "lob", "event_keys": ["lob:evt-1", "lob:evt-1"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["replayed"] == 1
    evt = fake_db.tables["webhook_events"][0]
    assert evt["replay_count"] == 1
    assert any(item.get("error") == "duplicate_request_key_ignored" for item in body["results"])
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


def test_lob_webhook_happy_path_projects_piece_status(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [],
            "company_direct_mail_pieces": [
                {
                    "id": "piece-row-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-lob",
                    "external_piece_id": "psc_123",
                    "piece_type": "postcard",
                    "status": "queued",
                    "deleted_at": None,
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", "lob_secret")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "enforce")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_tolerance_seconds", 300)
    client = TestClient(app)

    payload = {
        "id": "evt_lob_1",
        "type": "postcard.delivered",
        "version": "v1",
        "date_created": "2026-02-16T00:00:00Z",
        "body": {"resource": {"id": "psc_123", "object": "postcard", "metadata": {"job": "a"}}},
    }
    raw = json.dumps(payload, separators=(",", ":"))
    response = client.post("/api/webhooks/lob", data=raw, headers=_lob_signed_headers(raw, secret="lob_secret"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["event_type"] == "piece.delivered"
    assert body["signature_mode"] == "enforce"
    assert body["signature_verified"] is True
    assert body["signature_reason"] == "verified"

    piece = fake_db.tables["company_direct_mail_pieces"][0]
    assert piece["status"] == "delivered"
    assert len(fake_db.tables["webhook_events"]) == 1
    assert fake_db.tables["webhook_events"][0]["event_type"] == "piece.delivered"


def test_lob_webhook_duplicate_is_idempotent(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [],
            "company_direct_mail_pieces": [
                {
                    "id": "piece-row-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-lob",
                    "external_piece_id": "psc_123",
                    "piece_type": "postcard",
                    "status": "queued",
                    "deleted_at": None,
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", "lob_secret")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "enforce")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_tolerance_seconds", 300)
    client = TestClient(app)

    payload = {
        "id": "evt_lob_dup",
        "type": "postcard.processed",
        "date_created": "2026-02-16T00:00:00Z",
        "body": {"resource": {"id": "psc_123", "object": "postcard"}},
    }
    raw = json.dumps(payload, separators=(",", ":"))
    headers = _lob_signed_headers(raw, secret="lob_secret")
    first = client.post("/api/webhooks/lob", data=raw, headers=headers)
    second = client.post("/api/webhooks/lob", data=raw, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"
    assert second.json()["signature_mode"] == "enforce"
    assert second.json()["signature_verified"] is True
    assert len(fake_db.tables["webhook_events"]) == 1
    assert fake_db.tables["company_direct_mail_pieces"][0]["status"] == "ready_for_mail"


def test_lob_webhook_malformed_payload_handled_non_crashing(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": [], "company_direct_mail_pieces": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", None)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "permissive_audit")
    client = TestClient(app)

    response = client.post("/api/webhooks/lob", data="{invalid-json", headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dead_letter_recorded"
    assert body["event_type"] == "piece.unknown"
    assert body["signature_mode"] == "permissive_audit"
    assert body["signature_verified"] is False
    assert body["dead_letter"]["reason"] == "malformed_payload"
    assert len(fake_db.tables["webhook_events"]) == 1
    assert fake_db.tables["webhook_events"][0]["status"] == "dead_letter"
    assert fake_db.tables["webhook_events"][0]["payload"]["malformed_json"] is True


def test_lob_webhook_schema_invalid_dead_letters(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": [], "company_direct_mail_pieces": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", None)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "permissive_audit")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_schema_versions", "v1")
    client = TestClient(app)

    payload = {"id": "evt_schema_invalid", "type": "postcard.created", "date_created": "2026-02-16T00:00:00Z"}
    response = client.post("/api/webhooks/lob", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dead_letter_recorded"
    assert body["dead_letter"]["reason"] == "schema_invalid"
    assert fake_db.tables["webhook_events"][0]["payload"]["_schema_validation"]["status"] == "failed"


def test_lob_webhook_unknown_version_dead_letters(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": [], "company_direct_mail_pieces": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", None)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "permissive_audit")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_schema_versions", "v1")
    client = TestClient(app)

    payload = {
        "id": "evt_version_bad",
        "type": "postcard.created",
        "version": "v999",
        "date_created": "2026-02-16T00:00:00Z",
        "body": {"resource": {"id": "psc_100"}},
    }
    response = client.post("/api/webhooks/lob", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dead_letter_recorded"
    assert body["dead_letter"]["reason"] == "version_unsupported"
    assert fake_db.tables["webhook_events"][0]["payload"]["_schema_validation"]["reason"] == "version_unsupported"


def test_lob_replay_reprojects_piece_status(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [
                {
                    "id": "evt-row-lob-1",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-1",
                    "event_type": "piece.in_transit",
                    "replay_count": 0,
                    "payload": {
                        "id": "evt-1",
                        "type": "postcard.in_transit",
                        "resource_id": "psc_123",
                        "body": {"resource": {"id": "psc_123", "object": "postcard"}},
                    },
                }
            ],
            "company_direct_mail_pieces": [
                {
                    "id": "piece-row-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-lob",
                    "external_piece_id": "psc_123",
                    "piece_type": "postcard",
                    "status": "queued",
                    "deleted_at": None,
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    replay = client.post("/api/webhooks/replay/lob/lob:evt-1")
    assert replay.status_code == 200
    assert replay.json()["status"] == "replayed"
    assert replay.json()["provider_slug"] == "lob"
    assert fake_db.tables["company_direct_mail_pieces"][0]["status"] == "in_transit"
    assert fake_db.tables["webhook_events"][0]["replay_count"] == 1
    _clear_overrides()


def test_lob_webhook_unprojectable_event_goes_dead_letter(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": [], "company_direct_mail_pieces": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", None)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "permissive_audit")
    client = TestClient(app)

    payload = {
        "id": "evt_lob_unprojectable",
        "type": "self_mailer.processed",
        "date_created": "2026-02-16T00:00:00Z",
        "body": {"resource": {"id": "sfm_123", "object": "self_mailer"}},
    }
    response = client.post("/api/webhooks/lob", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dead_letter_recorded"
    assert body["dead_letter"]["reason"] == "projection_unresolved"
    assert len(fake_db.tables["webhook_events"]) == 1
    assert fake_db.tables["webhook_events"][0]["status"] == "dead_letter"


def test_lob_webhook_invalid_signature_rejected_in_enforce_mode(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": [], "company_direct_mail_pieces": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", "lob_secret")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "enforce")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_tolerance_seconds", 300)
    client = TestClient(app)

    payload = {"id": "evt_lob_bad_sig", "type": "postcard.created", "body": {"resource": {"id": "psc_123"}}}
    raw = json.dumps(payload, separators=(",", ":"))
    response = client.post(
        "/api/webhooks/lob",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Lob-Signature": "bad_signature",
            "Lob-Signature-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["type"] == "webhook_signature_invalid"
    assert response.json()["detail"]["reason"] == "invalid_signature"
    assert len(fake_db.tables["webhook_events"]) == 0


def test_lob_webhook_missing_signature_rejected_in_enforce_mode(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": [], "company_direct_mail_pieces": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", "lob_secret")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "enforce")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_tolerance_seconds", 300)
    client = TestClient(app)

    payload = {"id": "evt_lob_missing_sig", "type": "postcard.created", "body": {"resource": {"id": "psc_123"}}}
    raw = json.dumps(payload, separators=(",", ":"))
    response = client.post(
        "/api/webhooks/lob",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Lob-Signature-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["type"] == "webhook_signature_invalid"
    assert response.json()["detail"]["reason"] == "missing_signature"
    assert len(fake_db.tables["webhook_events"]) == 0


def test_lob_webhook_stale_timestamp_rejected_in_enforce_mode(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": [], "company_direct_mail_pieces": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", "lob_secret")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "enforce")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_tolerance_seconds", 300)
    client = TestClient(app)

    payload = {"id": "evt_lob_stale", "type": "postcard.created", "body": {"resource": {"id": "psc_123"}}}
    raw = json.dumps(payload, separators=(",", ":"))
    stale_ts = str(int(datetime.now(timezone.utc).timestamp()) - 3600)
    response = client.post("/api/webhooks/lob", data=raw, headers=_lob_signed_headers(raw, secret="lob_secret", timestamp=stale_ts))
    assert response.status_code == 401
    assert response.json()["detail"]["type"] == "webhook_signature_invalid"
    assert response.json()["detail"]["reason"] == "stale_timestamp"
    assert len(fake_db.tables["webhook_events"]) == 0


def test_lob_webhook_mode_switch_permissive_audit_does_not_reject(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [],
            "company_direct_mail_pieces": [
                {
                    "id": "piece-row-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-lob",
                    "external_piece_id": "psc_123",
                    "piece_type": "postcard",
                    "status": "queued",
                    "deleted_at": None,
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_secret", "lob_secret")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_mode", "permissive_audit")
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_signature_tolerance_seconds", 300)
    client = TestClient(app)

    payload = {
        "id": "evt_lob_permissive",
        "type": "postcard.created",
        "date_created": "2026-02-16T00:00:00Z",
        "body": {"resource": {"id": "psc_123"}},
    }
    raw = json.dumps(payload, separators=(",", ":"))
    response = client.post(
        "/api/webhooks/lob",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Lob-Signature": "bad_signature",
            "Lob-Signature-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["signature_mode"] == "permissive_audit"
    assert body["signature_verified"] is False
    assert body["signature_reason"] == "invalid_signature"


def test_lob_replay_bulk_guardrail_enforced(monkeypatch):
    fake_db = FakeSupabase({"providers": [{"id": "prov-lob", "slug": "lob"}], "webhook_events": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_max_events_per_run", 2)
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/webhooks/replay-bulk",
        json={"provider_slug": "lob", "event_keys": ["lob:e1", "lob:e2", "lob:e3"]},
    )
    assert response.status_code == 400
    assert "max events per run" in response.json()["detail"]
    _clear_overrides()


def test_lob_replay_query_batches_with_sleep(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [
                {
                    "id": "evt-row-lob-1",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-1",
                    "event_type": "piece.in_transit",
                    "replay_count": 0,
                    "created_at": "2026-02-15T10:00:00+00:00",
                    "payload": {"resource_id": "psc_1", "body": {"resource": {"id": "psc_1", "object": "postcard"}}},
                },
                {
                    "id": "evt-row-lob-2",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-2",
                    "event_type": "piece.processed",
                    "replay_count": 0,
                    "created_at": "2026-02-15T10:01:00+00:00",
                    "payload": {"resource_id": "psc_1", "body": {"resource": {"id": "psc_1", "object": "postcard"}}},
                },
                {
                    "id": "evt-row-lob-3",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-3",
                    "event_type": "piece.delivered",
                    "replay_count": 0,
                    "created_at": "2026-02-15T10:02:00+00:00",
                    "payload": {"resource_id": "psc_1", "body": {"resource": {"id": "psc_1", "object": "postcard"}}},
                },
            ],
            "company_direct_mail_pieces": [
                {
                    "id": "piece-row-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-lob",
                    "external_piece_id": "psc_1",
                    "piece_type": "postcard",
                    "status": "queued",
                    "deleted_at": None,
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_batch_size", 2)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_sleep_ms", 10)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_max_sleep_ms", 20)
    sleeps: list[float] = []
    monkeypatch.setattr(webhooks_router.time, "sleep", lambda value: sleeps.append(value))
    _set_super_admin()
    client = TestClient(app)

    response = client.post("/api/webhooks/replay-query", json={"provider_slug": "lob", "limit": 3})
    assert response.status_code == 200
    assert response.json()["replayed"] == 3
    assert len(sleeps) == 1
    assert sleeps[0] == 0.01
    _clear_overrides()


def test_lob_replay_backpressure_increases_sleep_on_transient_failures(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [
                {
                    "id": "evt-row-lob-a",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-a",
                    "event_type": "piece.in_transit",
                    "replay_count": 0,
                    "created_at": "2026-02-15T10:00:00+00:00",
                    "payload": {"resource_id": "psc_fail_a", "body": {"resource": {"id": "psc_fail_a", "object": "postcard"}}},
                },
                {
                    "id": "evt-row-lob-b",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-b",
                    "event_type": "piece.in_transit",
                    "replay_count": 0,
                    "created_at": "2026-02-15T10:01:00+00:00",
                    "payload": {"resource_id": "psc_fail_b", "body": {"resource": {"id": "psc_fail_b", "object": "postcard"}}},
                },
                {
                    "id": "evt-row-lob-c",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-c",
                    "event_type": "piece.in_transit",
                    "replay_count": 0,
                    "created_at": "2026-02-15T10:02:00+00:00",
                    "payload": {"resource_id": "psc_fail_c", "body": {"resource": {"id": "psc_fail_c", "object": "postcard"}}},
                },
            ],
            "company_direct_mail_pieces": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_batch_size", 1)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_sleep_ms", 10)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_max_sleep_ms", 40)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_backoff_multiplier", 2.0)
    monkeypatch.setattr(webhooks_router.settings, "lob_webhook_replay_max_concurrent_workers", 2)
    sleeps: list[float] = []
    monkeypatch.setattr(webhooks_router.time, "sleep", lambda value: sleeps.append(value))
    monkeypatch.setattr(
        webhooks_router,
        "_upsert_direct_mail_piece_from_lob_event",
        lambda **_: (_ for _ in ()).throw(Exception("timeout while projecting")),
    )
    _set_super_admin()
    client = TestClient(app)

    response = client.post("/api/webhooks/replay-query", json={"provider_slug": "lob", "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["replayed"] == 0
    assert len(sleeps) == 2
    assert sleeps[0] == 0.01
    assert sleeps[1] == 0.02
    _clear_overrides()


def test_lob_replay_bulk_marks_replay_failed_item(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [
                {
                    "id": "evt-row-lob-1",
                    "provider_slug": "lob",
                    "event_key": "lob:evt-fail",
                    "event_type": "piece.in_transit",
                    "replay_count": 0,
                    "payload": {"resource_id": "missing", "body": {"resource": {"id": "missing", "object": "postcard"}}},
                }
            ],
            "company_direct_mail_pieces": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    response = client.post("/api/webhooks/replay-bulk", json={"provider_slug": "lob", "event_keys": ["lob:evt-fail"]})
    assert response.status_code == 200
    body = response.json()
    assert body["replayed"] == 0
    assert body["results"][0]["status"] == "replay_failed"
    assert fake_db.tables["webhook_events"][0]["status"] == "dead_letter"
    _clear_overrides()


def test_lob_dead_letter_list_detail_and_replay(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-lob", "slug": "lob"}],
            "webhook_events": [
                {
                    "id": "evt-row-1",
                    "provider_slug": "lob",
                    "event_key": "lob:dl-1",
                    "event_type": "piece.failed",
                    "status": "dead_letter",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "replay_count": 0,
                    "last_error": "projection_unresolved",
                    "created_at": "2026-02-15T10:00:00+00:00",
                    "payload": {
                        "resource_id": "psc_1",
                        "_dead_letter": {"reason": "projection_unresolved", "retryable": False},
                        "body": {"resource": {"id": "psc_1", "object": "postcard"}},
                    },
                }
            ],
            "company_direct_mail_pieces": [
                {
                    "id": "piece-row-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "prov-lob",
                    "external_piece_id": "psc_1",
                    "piece_type": "postcard",
                    "status": "queued",
                    "deleted_at": None,
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    listed = client.get("/api/webhooks/dead-letters", params={"reason": "projection_unresolved", "replay_status": "pending"})
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["event_key"] == "lob:dl-1"
    assert rows[0]["dead_letter_reason"] == "projection_unresolved"

    detail = client.get("/api/webhooks/dead-letters/lob:dl-1")
    assert detail.status_code == 200
    assert detail.json()["status"] == "dead_letter"
    assert detail.json()["dead_letter_retryable"] is False

    replay = client.post("/api/webhooks/dead-letters/replay", json={"event_keys": ["lob:dl-1"]})
    assert replay.status_code == 200
    assert replay.json()["replayed"] == 1
    assert fake_db.tables["webhook_events"][0]["status"] == "replayed"
    assert fake_db.tables["webhook_events"][0]["replay_count"] == 1
    _clear_overrides()


def test_lob_dead_letter_list_filter_validation(monkeypatch):
    fake_db = FakeSupabase({"webhook_events": []})
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    invalid_status = client.get("/api/webhooks/dead-letters", params={"replay_status": "bad"})
    assert invalid_status.status_code == 400
    assert invalid_status.json()["detail"]["type"] == "invalid_filter"

    invalid_range = client.get(
        "/api/webhooks/dead-letters",
        params={
            "from_ts": "2026-02-20T00:00:00+00:00",
            "to_ts": "2026-02-01T00:00:00+00:00",
        },
    )
    assert invalid_range.status_code == 400
    assert invalid_range.json()["detail"]["type"] == "invalid_filter"
    _clear_overrides()


def test_lob_dead_letter_list_pagination_and_org_filter(monkeypatch):
    fake_db = FakeSupabase(
        {
            "webhook_events": [
                {
                    "id": "evt1",
                    "provider_slug": "lob",
                    "event_key": "lob:1",
                    "event_type": "piece.failed",
                    "status": "dead_letter",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "replay_count": 0,
                    "created_at": "2026-02-16T01:00:00+00:00",
                    "payload": {"_dead_letter": {"reason": "schema_invalid", "retryable": False}},
                },
                {
                    "id": "evt2",
                    "provider_slug": "lob",
                    "event_key": "lob:2",
                    "event_type": "piece.failed",
                    "status": "dead_letter",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "replay_count": 0,
                    "created_at": "2026-02-16T02:00:00+00:00",
                    "payload": {"_dead_letter": {"reason": "schema_invalid", "retryable": False}},
                },
                {
                    "id": "evt3",
                    "provider_slug": "lob",
                    "event_key": "lob:3",
                    "event_type": "piece.failed",
                    "status": "dead_letter",
                    "org_id": "org-2",
                    "company_id": "c-2",
                    "replay_count": 0,
                    "created_at": "2026-02-16T03:00:00+00:00",
                    "payload": {"_dead_letter": {"reason": "schema_invalid", "retryable": False}},
                },
            ]
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    _set_super_admin()
    client = TestClient(app)

    response = client.get("/api/webhooks/dead-letters", params={"org_id": "org-1", "limit": 1, "offset": 1})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["org_id"] == "org-1"
    _clear_overrides()
