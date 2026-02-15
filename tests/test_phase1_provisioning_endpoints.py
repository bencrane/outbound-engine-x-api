from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import SuperAdminContext
from src.auth.dependencies import get_current_super_admin
from src.main import app
from src.routers import internal_provisioning as provisioning_router


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
            if "id" not in payload:
                payload["id"] = f"{self.table_name}-id-{len(table)+1}"
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


def _set_super_admin_override():
    async def _override():
        return SuperAdminContext(super_admin_id="sa-1", email="sa@example.com")

    app.dependency_overrides[get_current_super_admin] = _override


def _clear_overrides():
    app.dependency_overrides.clear()


def test_provision_email_outreach_connected(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
            "capabilities": [{"id": "cap-email", "slug": "email_outreach"}],
            "providers": [{"id": "prov-smartlead", "slug": "smartlead", "capability_id": "cap-email"}],
            "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"smartlead": {"api_key": "sl-key"}}}],
            "company_entitlements": [],
        }
    )
    monkeypatch.setattr(provisioning_router, "supabase", fake_db)
    monkeypatch.setattr(provisioning_router, "validate_api_key", lambda _api_key: None)
    _set_super_admin_override()

    client = TestClient(app)
    response = client.post("/api/internal/provisioning/email-outreach/c-1", json={"smartlead_client_id": 12345})

    assert response.status_code == 200
    payload = response.json()
    assert payload["entitlement_status"] == "connected"
    assert payload["provisioning_state"] == "connected"
    assert payload["smartlead_client_id"] == 12345

    _clear_overrides()


def test_provision_email_outreach_pending_mapping(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
            "capabilities": [{"id": "cap-email", "slug": "email_outreach"}],
            "providers": [{"id": "prov-smartlead", "slug": "smartlead", "capability_id": "cap-email"}],
            "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"smartlead": {"api_key": "sl-key"}}}],
            "company_entitlements": [],
        }
    )
    monkeypatch.setattr(provisioning_router, "supabase", fake_db)
    monkeypatch.setattr(provisioning_router, "validate_api_key", lambda _api_key: None)
    _set_super_admin_override()

    client = TestClient(app)
    response = client.post("/api/internal/provisioning/email-outreach/c-1", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["entitlement_status"] == "entitled"
    assert payload["provisioning_state"] == "pending_client_mapping"
    assert payload["smartlead_client_id"] is None

    _clear_overrides()


def test_provision_email_outreach_failed_on_provider_validation(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
            "capabilities": [{"id": "cap-email", "slug": "email_outreach"}],
            "providers": [{"id": "prov-smartlead", "slug": "smartlead", "capability_id": "cap-email"}],
            "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"smartlead": {"api_key": "bad-key"}}}],
            "company_entitlements": [],
        }
    )
    monkeypatch.setattr(provisioning_router, "supabase", fake_db)

    def _raise(_api_key):
        raise provisioning_router.SmartleadProviderError("Invalid Smartlead API key")

    monkeypatch.setattr(provisioning_router, "validate_api_key", _raise)
    _set_super_admin_override()

    client = TestClient(app)
    response = client.post("/api/internal/provisioning/email-outreach/c-1", json={"smartlead_client_id": 555})

    assert response.status_code == 502
    assert "Provisioning failed" in response.json()["detail"]

    _clear_overrides()


def test_get_provisioning_status(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
            "capabilities": [{"id": "cap-email", "slug": "email_outreach"}],
            "providers": [{"id": "prov-smartlead", "slug": "smartlead", "capability_id": "cap-email"}],
            "company_entitlements": [
                {
                    "id": "ent-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "capability_id": "cap-email",
                    "provider_id": "prov-smartlead",
                    "status": "connected",
                    "provider_config": {"provisioning_state": "connected", "smartlead_client_id": 999},
                    "updated_at": _ts(),
                }
            ],
        }
    )
    monkeypatch.setattr(provisioning_router, "supabase", fake_db)
    _set_super_admin_override()

    client = TestClient(app)
    response = client.get("/api/internal/provisioning/email-outreach/c-1/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "smartlead"
    assert payload["provisioning_state"] == "connected"
    assert payload["smartlead_client_id"] == 999

    _clear_overrides()


def test_sync_inboxes_success(monkeypatch):
    fake_db = FakeSupabase(
        {
            "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
            "capabilities": [{"id": "cap-email", "slug": "email_outreach"}],
            "providers": [{"id": "prov-smartlead", "slug": "smartlead", "capability_id": "cap-email"}],
            "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"smartlead": {"api_key": "key"}}}],
            "company_entitlements": [
                {
                    "id": "ent-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "capability_id": "cap-email",
                    "provider_id": "prov-smartlead",
                    "status": "connected",
                    "provider_config": {"smartlead_client_id": 999, "provisioning_state": "connected"},
                    "updated_at": _ts(),
                }
            ],
            "company_inboxes": [],
        }
    )
    monkeypatch.setattr(provisioning_router, "supabase", fake_db)
    monkeypatch.setattr(
        provisioning_router,
        "list_email_accounts",
        lambda _api_key: [
            {"id": 10, "email": "a@example.com", "client_id": 999, "from_name": "A"},
            {"id": 11, "email": "b@example.com", "client_id": 111, "from_name": "B"},
        ],
    )
    _set_super_admin_override()

    client = TestClient(app)
    response = client.post("/api/internal/provisioning/email-outreach/c-1/sync-inboxes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["synced_count"] == 1
    assert payload["skipped_count"] == 1
    assert payload["smartlead_client_id"] == 999

    _clear_overrides()
