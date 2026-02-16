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
        self.operation = "select"
        self.filters = []
        self.update_payload = None

    def select(self, _fields: str):
        self.operation = "select"
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

    def execute(self):
        rows = list(self.db.tables.get(self.table_name, []))
        if self.operation == "update":
            updated = []
            for row in rows:
                matched = True
                for kind, key, value in self.filters:
                    if kind == "eq" and row.get(key) != value:
                        matched = False
                    elif kind == "is" and value == "null" and row.get(key) is not None:
                        matched = False
                if matched:
                    row.update(self.update_payload or {})
                    updated.append(dict(row))
            return FakeResponse(updated)
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
    if auth.role == "company_member" and auth.company_id:
        auth = AuthContext(
            org_id=auth.org_id,
            user_id=auth.user_id,
            role="company_admin",
            company_id=auth.company_id,
            token_id=auth.token_id,
            auth_method=auth.auth_method,
        )
    async def _override():
        return auth
    app.dependency_overrides[get_current_auth] = _override


def _clear():
    app.dependency_overrides.clear()


def _base_tables():
    return {
        "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
        "providers": [{"id": "p-emailbison", "slug": "emailbison"}],
        "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"emailbison": {"api_key": "eb-key", "instance_url": "https://eb.example"}}}],
        "company_inboxes": [
            {
                "id": "i-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "provider_id": "p-emailbison",
                "external_account_id": "25063",
                "email": "a@example.com",
                "display_name": "A",
                "status": "active",
                "warmup_enabled": True,
                "updated_at": _ts(),
                "deleted_at": None,
            }
        ],
    }


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


def test_get_sender_email_details_emailbison_happy_path(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    monkeypatch.setattr(
        inboxes_router,
        "emailbison_get_sender_email",
        lambda **kwargs: {"id": 25063, "email": "a@example.com", "status": "Connected"},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/inboxes/i-1/sender-email")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "email_outreach"
    assert body["sender_email"]["id"] == 25063

    _clear()


def test_get_sender_email_details_auth_boundary(monkeypatch):
    tables = _base_tables()
    tables["company_inboxes"][0]["company_id"] = "c-2"
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/inboxes/i-1/sender-email")
    assert response.status_code == 404

    _clear()


def test_get_sender_email_details_provider_error_shape_503(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)

    def _raise(**kwargs):
        raise inboxes_router.EmailBisonProviderError("EmailBison API returned HTTP 503: upstream unavailable")

    monkeypatch.setattr(inboxes_router, "emailbison_get_sender_email", _raise)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/inboxes/i-1/sender-email")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["type"] == "provider_error"
    assert detail["provider"] == "emailbison"
    assert detail["retryable"] is True

    _clear()


def test_update_sender_email_provider_error_shape_502(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)

    def _raise(**kwargs):
        raise inboxes_router.EmailBisonProviderError("Invalid EmailBison API key")

    monkeypatch.setattr(inboxes_router, "emailbison_update_sender_email", _raise)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.patch("/api/inboxes/i-1/sender-email", json={"name": "Updated"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["type"] == "provider_error"
    assert detail["provider"] == "emailbison"
    assert detail["retryable"] is False

    _clear()


def test_update_sender_email_happy_path_updates_local_display_name(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    monkeypatch.setattr(
        inboxes_router,
        "emailbison_update_sender_email",
        lambda **kwargs: {"id": 25063, "name": "Updated", "email": "a@example.com"},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.patch("/api/inboxes/i-1/sender-email", json={"name": "Updated"})
    assert response.status_code == 200
    assert fake_db.tables["company_inboxes"][0]["display_name"] == "Updated"

    _clear()


def test_warmup_malformed_payload_tolerance_non_numeric_external_account_id(monkeypatch):
    tables = _base_tables()
    tables["company_inboxes"][0]["external_account_id"] = "not-a-number"
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.patch("/api/inboxes/warmup/enable", json={"inbox_ids": ["i-1"]})
    assert response.status_code == 400
    assert "non-numeric external account id" in response.json()["detail"].lower()

    _clear()


def test_warmup_enable_disable_happy_path(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    monkeypatch.setattr(inboxes_router, "emailbison_enable_warmup_for_sender_emails", lambda **kwargs: {"success": True})
    monkeypatch.setattr(inboxes_router, "emailbison_disable_warmup_for_sender_emails", lambda **kwargs: {"success": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    enable = client.patch("/api/inboxes/warmup/enable", json={"inbox_ids": ["i-1"]})
    assert enable.status_code == 200
    assert fake_db.tables["company_inboxes"][0]["warmup_enabled"] is True

    disable = client.patch("/api/inboxes/warmup/disable", json={"inbox_ids": ["i-1"]})
    assert disable.status_code == 200
    assert fake_db.tables["company_inboxes"][0]["warmup_enabled"] is False

    _clear()


def test_warmup_detail_and_healthcheck_happy_path(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    monkeypatch.setattr(
        inboxes_router,
        "emailbison_get_sender_email_warmup_details",
        lambda **kwargs: {"id": 25063, "warmup_score": 88},
    )
    monkeypatch.setattr(
        inboxes_router,
        "emailbison_check_sender_email_mx_records",
        lambda **kwargs: {"email_host": "Google", "mx_records_valid": True},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    warmup = client.post("/api/inboxes/i-1/warmup", json={"start_date": "2026-02-01", "end_date": "2026-02-16"})
    assert warmup.status_code == 200
    assert warmup.json()["warmup"]["warmup_score"] == 88

    health = client.post("/api/inboxes/i-1/healthcheck/mx-records")
    assert health.status_code == 200
    assert health.json()["healthcheck"]["mx_records_valid"] is True

    _clear()


def test_bulk_missing_mx_records_admin_only(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(inboxes_router, "supabase", fake_db)
    monkeypatch.setattr(
        inboxes_router,
        "emailbison_bulk_check_missing_mx_records",
        lambda **kwargs: {"success": True},
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    denied = client.post("/api/inboxes/healthcheck/mx-records/bulk-missing")
    assert denied.status_code == 403

    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))
    allowed = client.post("/api/inboxes/healthcheck/mx-records/bulk-missing")
    assert allowed.status_code == 200

    _clear()
