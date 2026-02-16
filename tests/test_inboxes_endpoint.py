from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.routers import inboxes as inboxes_router


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

    def execute(self):
        rows = list(self.db.tables.get(self.table_name, []))
        for kind, key, value in self.filters:
            if kind == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif kind == "is" and value == "null":
                rows = [row for row in rows if row.get(key) is None]
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


def test_company_scoped_user_lists_own_inboxes(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
            "company_inboxes": [
                {
                    "id": "i-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "p-1",
                    "external_account_id": "10",
                    "email": "a@example.com",
                    "display_name": "A",
                    "status": "active",
                    "warmup_enabled": True,
                    "updated_at": _ts(),
                    "deleted_at": None,
                }
            ],
        }
    )
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/inboxes/")
    assert response.status_code == 200
    assert len(response.json()) == 1

    _clear()


def test_org_level_requires_admin_and_company_id(monkeypatch):
    fake_db = FakeSupabase({"companies": [], "company_inboxes": []})
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/inboxes/")
    assert response.status_code == 400

    _clear()


def test_org_admin_can_list_all_company_inboxes(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [
                {"id": "c-1", "org_id": "org-1", "deleted_at": None},
                {"id": "c-2", "org_id": "org-1", "deleted_at": None},
            ],
            "company_inboxes": [
                {
                    "id": "i-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_id": "p-1",
                    "external_account_id": "10",
                    "email": "a@example.com",
                    "display_name": "A",
                    "status": "active",
                    "warmup_enabled": True,
                    "updated_at": _ts(),
                    "deleted_at": None,
                },
                {
                    "id": "i-2",
                    "org_id": "org-1",
                    "company_id": "c-2",
                    "provider_id": "p-1",
                    "external_account_id": "11",
                    "email": "b@example.com",
                    "display_name": "B",
                    "status": "active",
                    "warmup_enabled": False,
                    "updated_at": _ts(),
                    "deleted_at": None,
                },
            ],
        }
    )
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/inboxes/?all_companies=true")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert {row["company_id"] for row in rows} == {"c-1", "c-2"}

    _clear()


def test_company_scoped_user_cannot_use_all_companies_on_inboxes(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
            "company_inboxes": [],
        }
    )
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/inboxes/?all_companies=true")
    assert response.status_code == 403
    assert response.json()["detail"] == "All-companies view is admin only"

    _clear()
