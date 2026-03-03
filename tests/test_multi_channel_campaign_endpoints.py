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
        self.filters: list[tuple[str, str, object]] = []
        self.insert_payload = None
        self.update_payload = None
        self.order_key: str | None = None
        self.order_desc = False
        self.limit_n: int | None = None

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

    def order(self, key: str, desc: bool = False):
        self.order_key = key
        self.order_desc = desc
        return self

    def limit(self, count: int):
        self.limit_n = count
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
            return FakeResponse([dict(payload)])

        if self.operation == "update":
            updated: list[dict] = []
            for row in table:
                if self._matches(row):
                    row.update(self.update_payload or {})
                    updated.append(dict(row))
            return FakeResponse(updated)

        rows = [dict(row) for row in table if self._matches(row)]
        if self.order_key:
            rows = sorted(rows, key=lambda row: row.get(self.order_key), reverse=self.order_desc)
        if self.limit_n is not None:
            rows = rows[: self.limit_n]
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
        "capabilities": [
            {"id": "cap-email", "slug": "email_outreach"},
            {"id": "cap-linkedin", "slug": "linkedin_outreach"},
            {"id": "cap-direct", "slug": "direct_mail"},
        ],
        "providers": [
            {"id": "prov-email", "slug": "smartlead", "capability_id": "cap-email"},
            {"id": "prov-linkedin", "slug": "heyreach", "capability_id": "cap-linkedin"},
            {"id": "prov-direct", "slug": "lob", "capability_id": "cap-direct"},
        ],
        "company_entitlements": [
            {
                "id": "ent-email",
                "org_id": "org-1",
                "company_id": "c-1",
                "capability_id": "cap-email",
                "provider_id": "prov-email",
                "deleted_at": None,
            },
            {
                "id": "ent-linkedin",
                "org_id": "org-1",
                "company_id": "c-1",
                "capability_id": "cap-linkedin",
                "provider_id": "prov-linkedin",
                "deleted_at": None,
            },
        ],
        "company_campaigns": [],
        "campaign_sequence_steps": [],
        "company_campaign_leads": [],
        "campaign_lead_progress": [],
        "campaign_lead_provider_ids": [],
    }


def _multi_campaign(status: str = "DRAFTED") -> dict:
    return {
        "id": "cmp-multi-1",
        "org_id": "org-1",
        "company_id": "c-1",
        "provider_id": None,
        "external_campaign_id": "",
        "name": "MC Campaign",
        "status": status,
        "campaign_type": "multi_channel",
        "created_by_user_id": "u-1",
        "created_at": _ts(),
        "updated_at": _ts(),
        "deleted_at": None,
    }


def test_create_multi_channel_campaign_success(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/multi-channel", json={"name": "MC", "campaign_type": "multi_channel"})

    assert response.status_code == 201
    body = response.json()
    assert body["campaign_type"] == "multi_channel"
    assert body["provider_id"] is None
    assert body["status"] == "DRAFTED"
    assert tables["company_campaigns"][0]["campaign_type"] == "multi_channel"
    _clear()


def test_create_multi_channel_campaign_fails_without_company_id_for_org_admin(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="org_admin", company_id=None, auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/multi-channel", json={"name": "MC"})

    assert response.status_code == 400
    assert "company_id is required" in response.json()["detail"]
    _clear()


def test_set_multi_channel_sequence_resolves_provider_ids(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="DRAFTED")]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.put(
        "/api/campaigns/cmp-multi-1/multi-channel-sequence",
        json={
            "steps": [
                {"step_order": 1, "channel": "email", "action_type": "send_email", "action_config": {}, "delay_days": 0},
                {
                    "step_order": 2,
                    "channel": "linkedin",
                    "action_type": "send_connection_request",
                    "action_config": {},
                    "delay_days": 2,
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["provider_id"] == "prov-email"
    assert body[1]["provider_id"] == "prov-linkedin"
    _clear()


def test_set_multi_channel_sequence_fails_if_campaign_active(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="ACTIVE")]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.put(
        "/api/campaigns/cmp-multi-1/multi-channel-sequence",
        json={"steps": [{"step_order": 1, "channel": "email", "action_type": "send_email", "action_config": {}}]},
    )

    assert response.status_code == 400
    _clear()


def test_set_multi_channel_sequence_fails_without_entitlement(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="DRAFTED")]
    tables["company_entitlements"] = [tables["company_entitlements"][0]]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.put(
        "/api/campaigns/cmp-multi-1/multi-channel-sequence",
        json={
            "steps": [
                {
                    "step_order": 1,
                    "channel": "linkedin",
                    "action_type": "send_connection_request",
                    "action_config": {},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "not entitled" in response.json()["detail"]
    _clear()


def test_add_multi_channel_leads(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="DRAFTED")]
    tables["campaign_sequence_steps"] = [
        {
            "id": "step-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-multi-1",
            "step_order": 1,
            "channel": "email",
            "provider_id": "prov-email",
            "action_type": "send_email",
            "action_config": {},
            "delay_days": 0,
            "execution_mode": "direct_single_touch",
            "deleted_at": None,
            "created_at": _ts(),
            "updated_at": _ts(),
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post(
        "/api/campaigns/cmp-multi-1/multi-channel-leads",
        json={"leads": [{"email": "lead@example.com", "first_name": "Lead"}]},
    )

    assert response.status_code == 200
    assert response.json()["affected"] == 1
    assert len(tables["company_campaign_leads"]) == 1
    assert tables["company_campaign_leads"][0]["provider_id"] == "prov-email"
    _clear()


def test_activate_multi_channel_campaign_success(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="DRAFTED")]
    tables["campaign_sequence_steps"] = [
        {
            "id": "step-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-multi-1",
            "step_order": 1,
            "channel": "email",
            "provider_id": "prov-email",
            "action_type": "send_email",
            "action_config": {},
            "delay_days": 0,
            "execution_mode": "direct_single_touch",
            "deleted_at": None,
            "created_at": _ts(),
            "updated_at": _ts(),
        }
    ]
    tables["company_campaign_leads"] = [
        {"id": "lead-1", "org_id": "org-1", "company_campaign_id": "cmp-multi-1", "deleted_at": None},
        {"id": "lead-2", "org_id": "org-1", "company_campaign_id": "cmp-multi-1", "deleted_at": None},
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/cmp-multi-1/activate")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["leads_initialized"] == 2
    assert len(tables["campaign_lead_progress"]) == 2
    assert all(row["step_status"] == "pending" for row in tables["campaign_lead_progress"])
    assert tables["company_campaigns"][0]["status"] == "ACTIVE"
    _clear()


def test_activate_multi_channel_campaign_fails_without_steps(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="DRAFTED")]
    tables["company_campaign_leads"] = [{"id": "lead-1", "org_id": "org-1", "company_campaign_id": "cmp-multi-1", "deleted_at": None}]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/cmp-multi-1/activate")

    assert response.status_code == 400
    assert "without sequence steps" in response.json()["detail"]
    _clear()


def test_activate_multi_channel_campaign_fails_without_leads(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="DRAFTED")]
    tables["campaign_sequence_steps"] = [
        {
            "id": "step-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-multi-1",
            "step_order": 1,
            "channel": "email",
            "provider_id": "prov-email",
            "action_type": "send_email",
            "action_config": {},
            "delay_days": 0,
            "execution_mode": "direct_single_touch",
            "deleted_at": None,
            "created_at": _ts(),
            "updated_at": _ts(),
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/cmp-multi-1/activate")

    assert response.status_code == 400
    assert "without leads" in response.json()["detail"]
    _clear()


def test_activate_multi_channel_campaign_fails_if_already_active(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="ACTIVE")]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post("/api/campaigns/cmp-multi-1/activate")

    assert response.status_code == 400
    _clear()


def test_get_multi_channel_lead_progress(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="ACTIVE")]
    tables["company_campaign_leads"] = [
        {
            "id": "lead-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "company_campaign_id": "cmp-multi-1",
            "provider_id": "prov-email",
            "external_lead_id": "",
            "status": "pending",
            "deleted_at": None,
            "updated_at": _ts(),
        }
    ]
    tables["campaign_lead_progress"] = [
        {
            "id": "progress-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-multi-1",
            "company_campaign_lead_id": "lead-1",
            "current_step_order": 1,
            "step_status": "pending",
            "next_execute_at": _ts(),
            "executed_at": None,
            "completed_at": None,
            "attempts": 0,
            "last_error": None,
        }
    ]
    tables["campaign_lead_provider_ids"] = [
        {
            "id": "lp-1",
            "org_id": "org-1",
            "company_campaign_lead_id": "lead-1",
            "provider_id": "prov-email",
            "external_id": "ext-123",
            "created_at": _ts(),
            "updated_at": _ts(),
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    list_response = client.get("/api/campaigns/cmp-multi-1/lead-progress")
    detail_response = client.get("/api/campaigns/cmp-multi-1/leads/lead-1/progress")

    assert list_response.status_code == 200
    list_body = list_response.json()
    assert len(list_body) == 1
    assert list_body[0]["lead_id"] == "lead-1"
    assert list_body[0]["step_status"] == "pending"

    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["lead_id"] == "lead-1"
    assert len(detail_body["provider_ids"]) == 1
    assert detail_body["provider_ids"][0]["provider_slug"] == "smartlead"
    _clear()


def test_list_campaigns_includes_multi_channel_campaign_type(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"] = [_multi_campaign(status="DRAFTED")]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="company_admin", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/campaigns/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["campaign_type"] == "multi_channel"
    assert body[0]["provider_id"] is None
    _clear()
