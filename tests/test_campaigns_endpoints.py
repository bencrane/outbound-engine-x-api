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
