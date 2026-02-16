from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.routers import analytics as analytics_router


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name: str, db: "FakeSupabase"):
        self.table_name = table_name
        self.db = db
        self.filters = []

    def select(self, _fields: str):
        return self

    def eq(self, key: str, value):
        self.filters.append(("eq", key, value))
        return self

    def is_(self, key: str, value):
        self.filters.append(("is", key, value))
        return self

    def gte(self, key: str, value):
        self.filters.append(("gte", key, value))
        return self

    def lte(self, key: str, value):
        self.filters.append(("lte", key, value))
        return self

    def execute(self):
        rows = list(self.db.tables.get(self.table_name, []))
        for kind, key, value in self.filters:
            if kind == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif kind == "is" and value == "null":
                rows = [row for row in rows if row.get(key) is None]
            elif kind == "gte":
                rows = [row for row in rows if (row.get(key) or "") >= value]
            elif kind == "lte":
                rows = [row for row in rows if (row.get(key) or "") <= value]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self, tables: dict):
        self.tables = tables

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def _set_auth(auth: AuthContext):
    async def _override():
        return auth

    app.dependency_overrides[get_current_auth] = _override


def _clear():
    app.dependency_overrides.clear()


def _base_tables():
    return {
        "company_campaigns": [
            {
                "id": "cmp-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "name": "Campaign 1",
                "status": "ACTIVE",
                "created_by_user_id": "u-1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "message_sync_status": "success",
                "last_message_sync_at": "2026-01-02T00:00:00+00:00",
                "last_message_sync_error": None,
                "provider_id": "prov-smartlead",
                "deleted_at": None,
            },
            {
                "id": "cmp-2",
                "org_id": "org-1",
                "company_id": "c-2",
                "name": "Campaign 2",
                "status": "ACTIVE",
                "created_by_user_id": "u-2",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "message_sync_status": "success",
                "last_message_sync_at": "2026-01-02T00:00:00+00:00",
                "last_message_sync_error": None,
                "provider_id": "prov-smartlead",
                "deleted_at": None,
            },
        ],
        "company_campaign_leads": [],
        "company_campaign_messages": [],
        "webhook_events": [],
    }


def test_analytics_endpoints_require_auth():
    client = TestClient(app)
    assert client.get("/api/analytics/campaigns").status_code == 401
    assert client.get("/api/analytics/clients").status_code == 401
    assert client.get("/api/analytics/reliability").status_code == 401
    assert client.get("/api/analytics/message-sync-health").status_code == 401
    assert client.get("/api/analytics/campaigns/cmp-1/sequence-steps").status_code == 401


def test_org_level_non_admin_blocked_from_analytics(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-org-user", role="user", company_id=None, auth_method="api_token"))
    client = TestClient(app)

    assert client.get("/api/analytics/campaigns").status_code == 403
    assert client.get("/api/analytics/clients").status_code == 403
    assert client.get("/api/analytics/reliability").status_code == 403
    assert client.get("/api/analytics/message-sync-health").status_code == 403
    assert client.get("/api/analytics/campaigns/cmp-1/sequence-steps").status_code == 403
    _clear()


def test_company_user_cannot_target_different_company_filters(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    assert client.get("/api/analytics/campaigns?company_id=c-2").status_code == 404
    assert client.get("/api/analytics/clients?company_id=c-2").status_code == 404
    assert client.get("/api/analytics/reliability?company_id=c-2").status_code == 404
    assert client.get("/api/analytics/message-sync-health?company_id=c-2").status_code == 404
    _clear()


def test_company_user_cannot_access_other_company_sequence_step_analytics(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    response = client.get("/api/analytics/campaigns/cmp-2/sequence-steps")
    assert response.status_code == 404
    assert response.json()["detail"] == "Campaign not found"
    _clear()


def test_company_user_can_access_own_analytics(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    assert client.get("/api/analytics/campaigns").status_code == 200
    assert client.get("/api/analytics/clients").status_code == 200
    assert client.get("/api/analytics/reliability").status_code == 200
    assert client.get("/api/analytics/message-sync-health").status_code == 200
    assert client.get("/api/analytics/campaigns/cmp-1/sequence-steps").status_code == 200
    _clear()
