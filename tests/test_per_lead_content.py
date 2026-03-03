from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.orchestrator import engine
from src.orchestrator.step_executor import StepExecutionResult
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

    def lte(self, key: str, value):
        self.filters.append(("lte", key, value))
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
            if kind == "lte":
                row_value = row.get(key)
                if row_value is None or str(row_value) > str(value):
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


def _set_auth():
    async def _override():
        return AuthContext(
            org_id="org-1",
            user_id="u-1",
            role="company_admin",
            company_id="c-1",
            auth_method="session",
        )

    app.dependency_overrides[get_current_auth] = _override


def _clear_auth():
    app.dependency_overrides.clear()


def _base_tables() -> dict:
    now = _ts()
    return {
        "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
        "company_campaigns": [
            {
                "id": "cmp-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "provider_id": None,
                "external_campaign_id": "",
                "name": "MC",
                "status": "DRAFTED",
                "campaign_type": "multi_channel",
                "created_by_user_id": "u-1",
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            }
        ],
        "campaign_sequence_steps": [
            {
                "id": "step-1",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "step_order": 1,
                "channel": "email",
                "provider_id": "prov-email",
                "action_type": "send_email",
                "action_config": {
                    "subject": "Default subject",
                    "message": "Default body",
                    "sender_email_id": 42,
                },
                "delay_days": 0,
                "execution_mode": "direct_single_touch",
                "deleted_at": None,
            },
            {
                "id": "step-2",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "step_order": 2,
                "channel": "linkedin",
                "provider_id": "prov-linkedin",
                "action_type": "send_connection_request",
                "action_config": {},
                "delay_days": 0,
                "execution_mode": "campaign_mediated",
                "deleted_at": None,
            },
        ],
        "company_campaign_leads": [],
        "campaign_lead_step_content": [],
        "campaign_lead_progress": [],
        "campaign_lead_provider_ids": [],
        "providers": [
            {"id": "prov-email", "slug": "emailbison"},
            {"id": "prov-linkedin", "slug": "heyreach"},
        ],
    }


def test_enroll_lead_with_per_step_content_creates_rows(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth()

    client = TestClient(app)
    response = client.post(
        "/api/campaigns/cmp-1/multi-channel-leads",
        json={
            "leads": [
                {
                    "email": "lead@example.com",
                    "first_name": "Ada",
                    "step_content": [
                        {"step_order": 1, "action_config_override": {"subject": "Hi Ada", "message": "Custom"}},
                        {"step_order": 2, "action_config_override": {"message": "LinkedIn opener"}},
                    ],
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["affected"] == 1
    assert len(tables["company_campaign_leads"]) == 1
    assert len(tables["campaign_lead_step_content"]) == 2
    _clear_auth()


def test_enroll_lead_without_step_content_remains_backward_compatible(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth()

    client = TestClient(app)
    response = client.post(
        "/api/campaigns/cmp-1/multi-channel-leads",
        json={"leads": [{"email": "lead@example.com", "first_name": "Ada"}]},
    )
    assert response.status_code == 200
    assert response.json()["affected"] == 1
    assert len(tables["company_campaign_leads"]) == 1
    assert tables["campaign_lead_step_content"] == []
    _clear_auth()


def test_put_step_content_for_existing_lead_upserts(monkeypatch):
    tables = _base_tables()
    tables["company_campaign_leads"] = [
        {
            "id": "lead-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "company_campaign_id": "cmp-1",
            "provider_id": "prov-email",
            "external_lead_id": "",
            "email": "lead@example.com",
            "status": "pending",
            "deleted_at": None,
        }
    ]
    tables["campaign_lead_step_content"] = [
        {
            "id": "content-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-1",
            "company_campaign_lead_id": "lead-1",
            "step_order": 1,
            "action_config_override": {"subject": "Old", "message": "Old"},
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth()

    client = TestClient(app)
    response = client.put(
        "/api/campaigns/cmp-1/leads/lead-1/step-content",
        json={
            "steps": [
                {"step_order": 1, "action_config_override": {"subject": "New subject", "message": "New body"}},
                {"step_order": 2, "action_config_override": {"message": "Second step"}},
            ]
        },
    )
    assert response.status_code == 200
    assert len(tables["campaign_lead_step_content"]) == 2
    updated = [row for row in tables["campaign_lead_step_content"] if row["step_order"] == 1][0]
    assert updated["action_config_override"]["subject"] == "New subject"
    _clear_auth()


def test_put_step_content_with_invalid_step_order_returns_400(monkeypatch):
    tables = _base_tables()
    tables["company_campaign_leads"] = [
        {
            "id": "lead-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "company_campaign_id": "cmp-1",
            "provider_id": "prov-email",
            "external_lead_id": "",
            "email": "lead@example.com",
            "status": "pending",
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth()

    client = TestClient(app)
    response = client.put(
        "/api/campaigns/cmp-1/leads/lead-1/step-content",
        json={"steps": [{"step_order": 99, "action_config_override": {"subject": "bad"}}]},
    )
    assert response.status_code == 400
    _clear_auth()


def test_get_step_content_returns_expected_shape(monkeypatch):
    tables = _base_tables()
    tables["company_campaign_leads"] = [
        {
            "id": "lead-1",
            "org_id": "org-1",
            "company_id": "c-1",
            "company_campaign_id": "cmp-1",
            "provider_id": "prov-email",
            "external_lead_id": "",
            "email": "lead@example.com",
            "status": "pending",
            "deleted_at": None,
        }
    ]
    tables["campaign_lead_step_content"] = [
        {
            "id": "content-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-1",
            "company_campaign_lead_id": "lead-1",
            "step_order": 1,
            "action_config_override": {"subject": "Personalized"},
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(campaigns_router, "supabase", fake_db)
    _set_auth()

    client = TestClient(app)
    response = client.get("/api/campaigns/cmp-1/leads/lead-1/step-content")
    assert response.status_code == 200
    body = response.json()
    assert body == [{"step_order": 1, "action_config_override": {"subject": "Personalized"}}]
    _clear_auth()


def test_orchestrator_uses_lead_override_when_present(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"][0]["status"] = "ACTIVE"
    tables["company_campaign_leads"] = [
        {
            "id": "lead-1",
            "company_campaign_id": "cmp-1",
            "email": "lead@example.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "deleted_at": None,
        }
    ]
    tables["campaign_lead_progress"] = [
        {
            "id": "progress-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-1",
            "company_campaign_lead_id": "lead-1",
            "current_step_id": "step-1",
            "current_step_order": 1,
            "step_status": "pending",
            "next_execute_at": _ts(),
            "attempts": 0,
            "updated_at": _ts(),
        }
    ]
    tables["campaign_lead_step_content"] = [
        {
            "id": "content-1",
            "org_id": "org-1",
            "company_campaign_id": "cmp-1",
            "company_campaign_lead_id": "lead-1",
            "step_order": 1,
            "action_config_override": {"subject": "Hey Ada", "message": "<p>Personalized</p>"},
        }
    ]
    fake_db = FakeSupabase(tables)
    captured: dict[str, object] = {}

    def _execute_step(**kwargs):
        captured["step"] = kwargs["step"]
        return StepExecutionResult(success=True, provider_slug="emailbison", action_type="send_email")

    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(engine, "execute_step", _execute_step)

    result = engine.run_orchestrator_tick(batch_size=10, dry_run=False)
    assert result.steps_executed == 1
    step = captured["step"]
    assert isinstance(step, dict)
    action_config = step["action_config"]
    assert action_config["subject"] == "Hey Ada"
    assert action_config["message"] == "<p>Personalized</p>"
    assert action_config["sender_email_id"] == 42


def test_orchestrator_uses_template_when_no_override_and_merge_logic():
    base = {"subject": "Default", "message": "Template", "sender_email_id": 42}
    merged = engine._merge_action_config(base, None)
    assert merged == base

    override = {"subject": "Custom", "message": "Personalized"}
    merged_override = engine._merge_action_config(base, override)
    assert merged_override["subject"] == "Custom"
    assert merged_override["message"] == "Personalized"
    assert merged_override["sender_email_id"] == 42
