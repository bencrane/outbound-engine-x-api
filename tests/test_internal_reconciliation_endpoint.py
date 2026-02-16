from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import SuperAdminContext
from src.auth.dependencies import get_current_super_admin
from src.main import app
from src.routers import internal_reconciliation as reconciliation_router


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name: str, db: "FakeSupabase"):
        self.table_name = table_name
        self.db = db
        self.operation = "select"
        self.filters = []
        self.insert_payload = None
        self.update_payload = None

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
            row = dict(self.insert_payload or {})
            row.setdefault("id", f"{self.table_name}-{len(table)+1}")
            row.setdefault("created_at", _ts())
            row.setdefault("updated_at", _ts())
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


def _clear():
    app.dependency_overrides.clear()


def _base_tables():
    return {
        "providers": [
            {"id": "prov-smartlead", "slug": "smartlead"},
            {"id": "prov-heyreach", "slug": "heyreach"},
        ],
        "organizations": [
            {
                "id": "org-1",
                "deleted_at": None,
                "provider_configs": {
                    "smartlead": {"api_key": "sl-key"},
                    "heyreach": {"api_key": "hr-key"},
                },
            }
        ],
        "company_entitlements": [
            {
                "id": "ent-sl",
                "org_id": "org-1",
                "company_id": "c-1",
                "provider_id": "prov-smartlead",
                "provider_config": {"smartlead_client_id": 999},
                "deleted_at": None,
            },
            {
                "id": "ent-hr",
                "org_id": "org-1",
                "company_id": "c-1",
                "provider_id": "prov-heyreach",
                "provider_config": {},
                "deleted_at": None,
            },
        ],
        "company_campaigns": [],
        "company_campaign_leads": [],
        "company_campaign_messages": [],
    }


def test_reconciliation_dry_run(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(reconciliation_router, "supabase", fake_db)
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_list_campaigns",
        lambda **kwargs: [{"id": 11, "name": "SL 1", "status": "ACTIVE", "client_id": 999}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_list_campaigns",
        lambda **kwargs: [{"id": "hr-1", "name": "HR 1", "status": "ACTIVE"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_leads",
        lambda **kwargs: [{"id": 1, "email": "a@x.com", "status": "active"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_replies",
        lambda **kwargs: [{"id": "r-1", "lead_id": 1, "subject": "Re: hello", "body": "reply", "direction": "inbound"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_lead_messages",
        lambda **kwargs: [{"id": "m-1", "lead_id": 1, "subject": "hello", "body": "outbound", "direction": "outbound"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_get_campaign_leads",
        lambda **kwargs: [{"id": "lead-1", "email": "b@x.com", "status": "contacted"}],
    )
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/campaigns-leads",
        json={"dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert len(body["providers"]) == 2
    assert len(fake_db.tables["company_campaigns"]) == 0
    assert len(fake_db.tables["company_campaign_leads"]) == 0
    assert len(fake_db.tables["company_campaign_messages"]) == 0
    _clear()


def test_reconciliation_apply_writes_data(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(reconciliation_router, "supabase", fake_db)
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_list_campaigns",
        lambda **kwargs: [{"id": 11, "name": "SL 1", "status": "ACTIVE", "client_id": 999}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_leads",
        lambda **kwargs: [{"id": 1, "email": "a@x.com", "status": "active"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_replies",
        lambda **kwargs: [{"id": "r-1", "lead_id": 1, "subject": "Re: hello", "body": "reply", "direction": "inbound"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_lead_messages",
        lambda **kwargs: [{"id": "m-1", "lead_id": 1, "subject": "hello", "body": "outbound", "direction": "outbound"}],
    )
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/campaigns-leads",
        json={"provider_slug": "smartlead", "dry_run": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    stats = body["providers"][0]
    assert stats["provider_slug"] == "smartlead"
    assert stats["campaigns_created"] == 1
    assert stats["leads_created"] == 1
    assert stats["messages_created"] == 2
    assert len(fake_db.tables["company_campaigns"]) == 1
    assert len(fake_db.tables["company_campaign_leads"]) == 1
    assert len(fake_db.tables["company_campaign_messages"]) == 2
    campaign = fake_db.tables["company_campaigns"][0]
    assert campaign["message_sync_status"] == "success"
    assert campaign["last_message_sync_error"] is None
    assert campaign.get("last_message_sync_at") is not None
    _clear()


def test_reconciliation_scheduled_requires_secret(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(reconciliation_router, "supabase", fake_db)
    monkeypatch.setattr(reconciliation_router.settings, "internal_scheduler_secret", "sched-secret")
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/run-scheduled",
        json={"provider_slug": "smartlead", "dry_run": True},
    )
    assert response.status_code == 401


def test_reconciliation_scheduled_runs_with_valid_secret(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(reconciliation_router, "supabase", fake_db)
    monkeypatch.setattr(reconciliation_router.settings, "internal_scheduler_secret", "sched-secret")
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_list_campaigns",
        lambda **kwargs: [{"id": 11, "name": "SL 1", "status": "ACTIVE", "client_id": 999}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_leads",
        lambda **kwargs: [{"id": 1, "email": "a@x.com", "status": "active"}],
    )
    monkeypatch.setattr(reconciliation_router, "smartlead_get_campaign_replies", lambda **kwargs: [])
    monkeypatch.setattr(reconciliation_router, "smartlead_get_campaign_lead_messages", lambda **kwargs: [])
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/run-scheduled",
        json={"provider_slug": "smartlead", "dry_run": False},
        headers={"X-Internal-Scheduler-Secret": "sched-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["providers"][0]["campaigns_created"] == 1
    assert len(fake_db.tables["company_campaigns"]) == 1


def test_reconciliation_message_limit_caps_upserts(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(reconciliation_router, "supabase", fake_db)
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_list_campaigns",
        lambda **kwargs: [{"id": 11, "name": "SL 1", "status": "ACTIVE", "client_id": 999}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_leads",
        lambda **kwargs: [{"id": 1, "email": "a@x.com", "status": "active"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_replies",
        lambda **kwargs: [{"id": "r-1", "lead_id": 1, "direction": "inbound"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "smartlead_get_campaign_lead_messages",
        lambda **kwargs: [{"id": "m-1", "lead_id": 1, "direction": "outbound"}],
    )
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/campaigns-leads",
        json={"provider_slug": "smartlead", "dry_run": False, "message_limit": 1},
    )
    assert response.status_code == 200
    body = response.json()
    stats = body["providers"][0]
    assert stats["messages_scanned"] == 1
    assert stats["messages_created"] == 1
    assert len(fake_db.tables["company_campaign_messages"]) == 1
    _clear()


def test_reconciliation_heyreach_webhook_only_skips_message_pull(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(reconciliation_router, "supabase", fake_db)
    monkeypatch.setattr(reconciliation_router.settings, "heyreach_message_sync_mode", "webhook_only")
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_list_campaigns",
        lambda **kwargs: [{"id": "hr-1", "name": "HR 1", "status": "ACTIVE"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_get_campaign_leads",
        lambda **kwargs: [{"id": "lead-1", "email": "hr@example.com", "status": "contacted"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_get_campaign_lead_messages",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Should not be called in webhook_only mode")),
    )
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/campaigns-leads",
        json={"provider_slug": "heyreach", "dry_run": False, "sync_messages": True},
    )
    assert response.status_code == 200
    body = response.json()
    stats = body["providers"][0]
    assert stats["messages_scanned"] == 0
    assert stats["messages_created"] == 0
    assert len(fake_db.tables["company_campaign_messages"]) == 0
    campaign = fake_db.tables["company_campaigns"][0]
    assert campaign["message_sync_status"] == "skipped_webhook_only"
    assert campaign["last_message_sync_error"] is None
    _clear()


def test_reconciliation_heyreach_pull_best_effort_upserts_messages(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(reconciliation_router, "supabase", fake_db)
    monkeypatch.setattr(reconciliation_router.settings, "heyreach_message_sync_mode", "pull_best_effort")
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_list_campaigns",
        lambda **kwargs: [{"id": "hr-1", "name": "HR 1", "status": "ACTIVE"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_get_campaign_leads",
        lambda **kwargs: [{"id": "lead-1", "email": "hr@example.com", "status": "contacted"}],
    )
    monkeypatch.setattr(
        reconciliation_router,
        "heyreach_get_campaign_lead_messages",
        lambda **kwargs: [{"id": "hr-msg-1", "leadId": "lead-1", "message": "Hi there", "direction": "outbound"}],
    )
    _set_super_admin()
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/campaigns-leads",
        json={"provider_slug": "heyreach", "dry_run": False, "sync_messages": True},
    )
    assert response.status_code == 200
    body = response.json()
    stats = body["providers"][0]
    assert stats["messages_scanned"] == 1
    assert stats["messages_created"] == 1
    assert len(fake_db.tables["company_campaign_messages"]) == 1
    _clear()
