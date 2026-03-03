from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.main import app
from src.orchestrator import event_bridge
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
        self.filters: list[tuple[str, str, object]] = []
        self.limit_count: int | None = None

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

    def limit(self, value: int):
        self.limit_count = value
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
            row = dict(self.insert_payload or {})
            row.setdefault("id", f"{self.table_name}-{len(table)+1}")
            table.append(row)
            return FakeResponse([dict(row)])
        if self.operation == "update":
            updated = []
            for row in table:
                if self._matches(row):
                    row.update(self.update_payload or {})
                    updated.append(dict(row))
            return FakeResponse(updated)
        rows = [dict(row) for row in table if self._matches(row)]
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_reply_event_on_multi_channel_campaign_accelerates_next_execute_at(monkeypatch):
    far_future = datetime.now(timezone.utc) + timedelta(days=10)
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "co-1",
                    "campaign_type": "multi_channel",
                    "deleted_at": None,
                }
            ],
            "campaign_lead_progress": [
                {
                    "id": "prog-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "company_campaign_lead_id": "lead-1",
                    "current_step_order": 2,
                    "step_status": "pending",
                    "next_execute_at": far_future.isoformat(),
                }
            ],
            "campaign_events": [],
        }
    )
    monkeypatch.setattr(event_bridge, "supabase", fake_db)

    affected = event_bridge.process_engagement_event(
        org_id="org-1",
        campaign_id="cmp-1",
        lead_id="lead-1",
        event_type="lead_replied",
        provider_slug="smartlead",
        payload={"event": "lead_replied"},
    )
    assert affected == 1
    accelerated = _parse_ts(fake_db.tables["campaign_lead_progress"][0]["next_execute_at"])
    assert accelerated is not None
    assert accelerated < datetime.now(timezone.utc) + timedelta(seconds=5)


def test_event_on_single_channel_campaign_returns_zero(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "co-1",
                    "campaign_type": "single_channel",
                    "deleted_at": None,
                }
            ],
            "campaign_lead_progress": [],
            "campaign_events": [],
        }
    )
    monkeypatch.setattr(event_bridge, "supabase", fake_db)
    affected = event_bridge.process_engagement_event(
        org_id="org-1",
        campaign_id="cmp-1",
        lead_id="lead-1",
        event_type="reply_received",
        provider_slug="smartlead",
        payload={},
    )
    assert affected == 0
    assert fake_db.tables["campaign_events"] == []


def test_event_with_no_matching_lead_returns_zero(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "co-1",
                    "campaign_type": "multi_channel",
                    "deleted_at": None,
                }
            ],
            "campaign_lead_progress": [],
            "campaign_events": [],
        }
    )
    monkeypatch.setattr(event_bridge, "supabase", fake_db)
    affected = event_bridge.process_engagement_event(
        org_id="org-1",
        campaign_id="cmp-1",
        lead_id="missing",
        event_type="reply_received",
        provider_slug="smartlead",
        payload={},
    )
    assert affected == 0


def test_campaign_event_row_is_created(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "co-1",
                    "campaign_type": "multi_channel",
                    "deleted_at": None,
                }
            ],
            "campaign_lead_progress": [],
            "campaign_events": [],
        }
    )
    monkeypatch.setattr(event_bridge, "supabase", fake_db)

    event_bridge.process_engagement_event(
        org_id="org-1",
        campaign_id="cmp-1",
        lead_id=None,
        event_type="campaign_event",
        provider_slug="heyreach",
        payload={"foo": "bar"},
    )
    assert len(fake_db.tables["campaign_events"]) == 1
    row = fake_db.tables["campaign_events"][0]
    assert row["company_campaign_id"] == "cmp-1"
    assert row["provider_slug"] == "heyreach"
    assert row["channel"] == "linkedin"


def test_event_bridge_failure_does_not_propagate_to_webhook_ingestion(monkeypatch):
    fake_db = FakeSupabase(
        {
            "providers": [{"id": "prov-1", "slug": "smartlead"}],
            "webhook_events": [],
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "co-1",
                    "provider_id": "prov-1",
                    "external_campaign_id": "ext-1",
                    "campaign_type": "multi_channel",
                    "status": "ACTIVE",
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [
                {
                    "id": "lead-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "external_lead_id": "lead-ext-1",
                    "status": "active",
                    "deleted_at": None,
                }
            ],
            "company_campaign_messages": [],
            "campaign_events": [],
        }
    )
    monkeypatch.setattr(webhooks_router, "supabase", fake_db)
    monkeypatch.setattr(webhooks_router.settings, "smartlead_webhook_secret", None)
    monkeypatch.setattr(webhooks_router.settings, "heyreach_webhook_secret", None)
    monkeypatch.setattr(
        webhooks_router,
        "process_engagement_event",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("bridge down")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/webhooks/smartlead",
        json={
            "event": "lead_replied",
            "campaign_id": "ext-1",
            "lead_id": "lead-ext-1",
            "message_id": "msg-1",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "processed"
