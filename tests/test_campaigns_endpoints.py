from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.routers import campaigns as campaigns_router


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
            payload = dict(self.insert_payload or {})
            payload.setdefault("id", f"{self.table_name}-{len(table)+1}")
            payload.setdefault("created_at", _ts())
            payload.setdefault("updated_at", _ts())
            table.append(payload)
            return FakeResponse([payload])

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


def _set_auth(auth: AuthContext):
    async def _override():
        return auth
    app.dependency_overrides[get_current_auth] = _override


def _clear():
    app.dependency_overrides.clear()


def _base_tables():
    return {
        "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
        "capabilities": [{"id": "cap-email", "slug": "email_outreach"}],
        "providers": [{"id": "prov-smartlead", "slug": "smartlead", "capability_id": "cap-email"}],
        "company_entitlements": [{
            "id": "ent-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "capability_id": "cap-email",
            "provider_id": "prov-smartlead",
            "status": "connected",
            "provider_config": {"smartlead_client_id": 999},
            "updated_at": _ts(),
        }],
        "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"smartlead": {"api_key": "sl-key"}}}],
        "company_campaigns": [],
        "company_campaign_sequences": [],
    }


def test_create_campaign_success(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_create_campaign",
        lambda api_key, name, client_id: {"id": 42, "name": name, "status": "DRAFTED"},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/", json={"name": "Q1 Campaign"})

    assert response.status_code == 201
    body = response.json()
    assert body["external_campaign_id"] == "42"
    assert body["name"] == "Q1 Campaign"
    assert body["status"] == "DRAFTED"

    _clear()


def test_create_campaign_normalizes_provider_status(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_create_campaign",
        lambda api_key, name, client_id: {"id": 99, "name": name, "status": "started"},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/", json={"name": "Normalize Me"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ACTIVE"

    _clear()


def test_list_campaigns_mine_only(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "1",
            "name": "Mine",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        },
        {
            "id": "cmp-2",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "2",
            "name": "Other",
            "status": "PAUSED",
            "created_by_user_id": "u-2",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        },
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/campaigns/?mine_only=true")
    assert response.status_code == 200
    campaigns = response.json()
    assert len(campaigns) == 1
    assert campaigns[0]["id"] == "cmp-1"

    _clear()


def test_update_campaign_status_success(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "DRAFTED",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_update_campaign_status",
        lambda api_key, campaign_id, status_value: {"id": int(campaign_id), "status": status_value},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/cmp-1/status", json={"status": "ACTIVE"})
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"

    _clear()


def test_save_campaign_sequence_success(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "DRAFTED",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_save_campaign_sequence",
        lambda api_key, campaign_id, sequence: {"ok": True, "campaign_id": campaign_id},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post(
        "/api/campaigns/cmp-1/sequence",
        json={"sequence": [{"seq_number": 1, "subject": "Hi", "email_body": "Body"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["sequence"][0]["seq_number"] == 1

    _clear()


def test_get_campaign_sequence_falls_back_to_local_snapshot(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    tables["company_campaign_sequences"] = [
        {
            "id": "seq-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-1",
            "version": 1,
            "sequence_payload": [{"seq_number": 1, "subject": "cached"}],
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)

    def _raise(*args, **kwargs):
        raise campaigns_router.SmartleadProviderError("endpoint missing")

    monkeypatch.setattr(campaigns_router, "smartlead_get_campaign_sequence", _raise)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/campaigns/cmp-1/sequence")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "local_snapshot"
    assert body["sequence"][0]["subject"] == "cached"

    _clear()


def test_add_campaign_leads_and_list(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    tables["company_campaign_leads"] = []
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(campaigns_router, "smartlead_add_campaign_leads", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_get_campaign_leads",
        lambda **kwargs: [{"id": 77, "email": "lead@example.com", "first_name": "Lead", "status": "active"}],
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    add_response = client.post(
        "/api/campaigns/cmp-1/leads",
        json={"leads": [{"email": "lead@example.com", "first_name": "Lead"}]},
    )
    assert add_response.status_code == 200
    assert add_response.json()["affected"] == 1

    list_response = client.get("/api/campaigns/cmp-1/leads")
    assert list_response.status_code == 200
    leads = list_response.json()
    assert len(leads) == 1
    assert leads[0]["email"] == "lead@example.com"

    _clear()


def test_pause_resume_unsubscribe_campaign_lead(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    tables["company_campaign_leads"] = [
        {
            "id": "lead-local-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "company_campaign_id": "cmp-1",
            "provider_id": "prov-smartlead",
            "external_lead_id": "77",
            "email": "lead@example.com",
            "status": "active",
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(campaigns_router, "smartlead_pause_campaign_lead", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(campaigns_router, "smartlead_resume_campaign_lead", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(campaigns_router, "smartlead_unsubscribe_campaign_lead", lambda **kwargs: {"ok": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    pause = client.post("/api/campaigns/cmp-1/leads/lead-local-1/pause")
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"

    resume = client.post("/api/campaigns/cmp-1/leads/lead-local-1/resume")
    assert resume.status_code == 200
    assert resume.json()["status"] == "active"

    unsub = client.post("/api/campaigns/cmp-1/leads/lead-local-1/unsubscribe")
    assert unsub.status_code == 200
    assert unsub.json()["status"] == "unsubscribed"

    _clear()


def test_list_campaign_replies_with_provider_sync(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    tables["company_campaign_messages"] = []
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_get_campaign_replies",
        lambda **kwargs: [{"id": 501, "subject": "Re: hello", "body": "reply", "lead_id": "77"}],
    )
    tables["company_campaign_leads"] = [
        {
            "id": "lead-local-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "company_campaign_id": "cmp-1",
            "provider_id": "prov-smartlead",
            "external_lead_id": "77",
            "status": "active",
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/campaigns/cmp-1/replies")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["direction"] == "inbound"
    assert data[0]["subject"] == "Re: hello"

    _clear()


def test_list_campaign_lead_messages_with_provider_sync(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    tables["company_campaign_leads"] = [
        {
            "id": "lead-local-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "company_campaign_id": "cmp-1",
            "provider_id": "prov-smartlead",
            "external_lead_id": "77",
            "status": "active",
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    tables["company_campaign_messages"] = []
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_get_campaign_lead_messages",
        lambda **kwargs: [{"id": 601, "direction": "outbound", "subject": "Hello", "body": "Message"}],
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/campaigns/cmp-1/leads/lead-local-1/messages")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["subject"] == "Hello"

    _clear()


def test_campaign_analytics_summary(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    tables["company_campaign_leads"] = [
        {"id": "l1", "org_id": "org-1", "company_campaign_id": "cmp-1", "status": "active", "updated_at": _ts(), "deleted_at": None},
        {"id": "l2", "org_id": "org-1", "company_campaign_id": "cmp-1", "status": "paused", "updated_at": _ts(), "deleted_at": None},
        {"id": "l3", "org_id": "org-1", "company_campaign_id": "cmp-1", "status": "unsubscribed", "updated_at": _ts(), "deleted_at": None},
    ]
    tables["company_campaign_messages"] = [
        {"id": "m1", "org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "outbound", "updated_at": _ts(), "deleted_at": None},
        {"id": "m2", "org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "inbound", "updated_at": _ts(), "deleted_at": None},
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/campaigns/cmp-1/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["leads_total"] == 3
    assert body["replies_total"] == 1
    assert body["outbound_messages_total"] == 1
    assert body["reply_rate"] == 100.0

    _clear()


def test_campaign_analytics_provider(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "123",
            "name": "Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    monkeypatch.setattr(
        campaigns_router,
        "smartlead_get_campaign_analytics",
        lambda **kwargs: {"sent_count": 10, "open_count": 5, "reply_count": 2, "bounce_count": 1},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/campaigns/cmp-1/analytics/provider")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "smartlead"
    assert body["normalized"]["sent"] == 10
    assert body["normalized"]["replied"] == 2

    _clear()
