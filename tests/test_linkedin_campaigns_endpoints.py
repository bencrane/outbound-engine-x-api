from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.routers import linkedin_campaigns as linkedin_router


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
        "capabilities": [{"id": "cap-li", "slug": "linkedin_outreach"}],
        "providers": [{"id": "prov-heyreach", "slug": "heyreach", "capability_id": "cap-li"}],
        "company_entitlements": [
            {
                "id": "ent-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "capability_id": "cap-li",
                "provider_id": "prov-heyreach",
                "status": "connected",
                "provider_config": {},
                "deleted_at": None,
                "updated_at": _ts(),
            }
        ],
        "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"heyreach": {"api_key": "hr-key"}}}],
        "company_campaigns": [],
        "company_campaign_leads": [],
        "company_campaign_messages": [],
    }


def test_create_linkedin_campaign_success(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    monkeypatch.setattr(
        linkedin_router,
        "heyreach_create_campaign",
        lambda **kwargs: {"id": "hr-1", "name": kwargs["name"], "status": "ACTIVE"},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/linkedin/campaigns/", json={"name": "LinkedIn Q1"})
    assert response.status_code == 201
    body = response.json()
    assert body["external_campaign_id"] == "hr-1"
    assert body["status"] == "ACTIVE"
    _clear()


def test_pause_linkedin_campaign(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-li-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-heyreach",
            "external_campaign_id": "hr-1",
            "name": "LinkedIn Q1",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    monkeypatch.setattr(linkedin_router, "heyreach_pause_campaign", lambda **kwargs: {"ok": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/linkedin/campaigns/cmp-li-1/action", json={"action": "pause"})
    assert response.status_code == 200
    assert response.json()["status"] == "PAUSED"
    _clear()


def test_add_linkedin_leads_and_update_status(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-li-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-heyreach",
            "external_campaign_id": "hr-1",
            "name": "LinkedIn Q1",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    monkeypatch.setattr(linkedin_router, "heyreach_add_campaign_leads", lambda **kwargs: {"addedCount": 1})
    monkeypatch.setattr(
        linkedin_router,
        "heyreach_get_campaign_leads",
        lambda **kwargs: [
            {
                "id": "lead-7",
                "email": "li@example.com",
                "firstName": "Li",
                "lastName": "User",
                "status": "contacted",
            }
        ],
    )
    monkeypatch.setattr(linkedin_router, "heyreach_update_lead_status", lambda **kwargs: {"ok": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    add_resp = client.post(
        "/api/linkedin/campaigns/cmp-li-1/leads",
        json={"leads": [{"email": "li@example.com", "first_name": "Li"}]},
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["affected"] == 1

    leads_resp = client.get("/api/linkedin/campaigns/cmp-li-1/leads")
    assert leads_resp.status_code == 200
    lead_id = leads_resp.json()[0]["id"]

    status_resp = client.post(
        f"/api/linkedin/campaigns/cmp-li-1/leads/{lead_id}/status",
        json={"status": "connected"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "connected"
    _clear()


def test_linkedin_campaign_metrics(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [
        {
            "id": "cmp-li-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-heyreach",
            "external_campaign_id": "hr-1",
            "name": "LinkedIn Q1",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    monkeypatch.setattr(
        linkedin_router,
        "heyreach_get_campaign_metrics",
        lambda **kwargs: {
            "totalLeads": 20,
            "contacted": 15,
            "replied": 3,
            "connected": 5,
            "responseRate": 20.0,
            "connectionRate": 33.3,
        },
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/linkedin/campaigns/cmp-li-1/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "heyreach"
    assert body["normalized"]["total_leads"] == 20
    assert body["normalized"]["connected"] == 5
    _clear()


def test_linkedin_org_level_non_admin_cannot_create(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-2", role="user", company_id=None, auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/linkedin/campaigns/", json={"name": "Denied", "company_id": "c-1"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin role required"
    _clear()


def test_linkedin_org_admin_requires_company_id_for_list(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/linkedin/campaigns/")
    assert response.status_code == 400
    assert "company_id is required" in response.json()["detail"]
    _clear()


def test_linkedin_org_admin_can_list_all_companies(monkeypatch):
    tables = _base_tables()
    tables["companies"].append({"id": "c-2", "org_id": "org-1", "deleted_at": None})
    tables["providers"].append({"id": "prov-smartlead", "slug": "smartlead", "capability_id": "cap-email"})
    tables["company_campaigns"] = [
        {
            "id": "cmp-li-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-heyreach",
            "external_campaign_id": "hr-1",
            "name": "LinkedIn C1",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        },
        {
            "id": "cmp-li-2",
            "org_id": "org-1",
            "company_id": "c-2",
            "provider_id": "prov-heyreach",
            "external_campaign_id": "hr-2",
            "name": "LinkedIn C2",
            "status": "PAUSED",
            "created_by_user_id": "u-2",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        },
        {
            "id": "cmp-email-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "provider_id": "prov-smartlead",
            "external_campaign_id": "sl-1",
            "name": "Email C1",
            "status": "ACTIVE",
            "created_by_user_id": "u-1",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        },
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/linkedin/campaigns/?all_companies=true")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert {row["company_id"] for row in rows} == {"c-1", "c-2"}
    assert all(row["provider_id"] == "prov-heyreach" for row in rows)
    _clear()


def test_linkedin_company_scoped_user_cannot_use_all_companies(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/linkedin/campaigns/?all_companies=true")
    assert response.status_code == 403
    assert response.json()["detail"] == "All-companies view is admin only"
    _clear()


def test_linkedin_org_admin_cannot_combine_all_companies_and_company_id(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/linkedin/campaigns/?all_companies=true&company_id=c-1")
    assert response.status_code == 400
    assert "cannot be combined with all_companies=true" in response.json()["detail"]
    _clear()


def test_linkedin_company_user_cannot_target_different_company(monkeypatch):
    tables = _base_tables()
    tables["companies"].append({"id": "c-2", "org_id": "org-1", "deleted_at": None})
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/linkedin/campaigns/", json={"name": "Blocked", "company_id": "c-2"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Company not found"
    _clear()


def test_linkedin_company_user_cannot_access_other_company_campaign(monkeypatch):
    tables = _base_tables()
    tables["companies"].append({"id": "c-2", "org_id": "org-1", "deleted_at": None})
    tables["company_campaigns"] = [
        {
            "id": "cmp-li-2",
            "org_id": "org-1",
            "company_id": "c-2",
            "provider_id": "prov-heyreach",
            "external_campaign_id": "hr-2",
            "name": "Other Company Campaign",
            "status": "ACTIVE",
            "created_by_user_id": "u-9",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/linkedin/campaigns/cmp-li-2")
    assert response.status_code == 404
    assert response.json()["detail"] == "Campaign not found"
    _clear()


def test_linkedin_create_maps_transient_provider_errors_to_503(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(linkedin_router, "supabase", fake_db)

    def _raise_transient(**kwargs):
        raise linkedin_router.HeyReachProviderError("HeyReach API returned HTTP 503: upstream unavailable")

    monkeypatch.setattr(linkedin_router, "heyreach_create_campaign", _raise_transient)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/linkedin/campaigns/", json={"name": "LinkedIn transient"})
    assert response.status_code == 503
    assert "transient" in response.json()["detail"]
    _clear()
