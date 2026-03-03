from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.orchestrator import conditions
from src.orchestrator import engine
from src.orchestrator.step_executor import StepExecutionResult


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
        self.order_by: str | None = None
        self.limit_count: int | None = None

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

    def order(self, key: str):
        self.order_by = key
        return self

    def limit(self, value: int):
        self.limit_count = value
        return self

    def _matches(self, row: dict) -> bool:
        for kind, key, value in self.filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "is" and value == "null" and row.get(key) is not None:
                return False
            if kind == "lte":
                row_value = row.get(key)
                if row_value is None:
                    return False
                row_ts = _parse_ts(str(row_value))
                cmp_ts = _parse_ts(str(value))
                if row_ts is None or cmp_ts is None:
                    return False
                if row_ts > cmp_ts:
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
            return FakeResponse([dict(row)])

        if self.operation == "update":
            updated = []
            for row in table:
                if self._matches(row):
                    row.update(self.update_payload or {})
                    updated.append(dict(row))
            return FakeResponse(updated)

        rows = [dict(row) for row in table if self._matches(row)]
        if self.order_by:
            rows.sort(key=lambda row: row.get(self.order_by))
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self, tables: dict):
        self.tables = tables

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _base_tables(with_inbound_reply: bool) -> dict[str, list[dict]]:
    now = datetime.now(timezone.utc)
    messages: list[dict] = []
    if with_inbound_reply:
        messages.append(
            {
                "id": "msg-1",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "company_campaign_lead_id": "lead-1",
                "direction": "inbound",
                "deleted_at": None,
            }
        )
    return {
        "company_campaigns": [
            {
                "id": "cmp-1",
                "org_id": "org-1",
                "company_id": "co-1",
                "deleted_at": None,
            }
        ],
        "company_campaign_leads": [
            {
                "id": "lead-1",
                "company_campaign_id": "cmp-1",
                "org_id": "org-1",
                "email": "lead@example.com",
                "deleted_at": None,
            }
        ],
        "campaign_sequence_steps": [
            {
                "id": "step-2",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "step_order": 2,
                "channel": "email",
                "provider_id": "prov-email",
                "action_type": "send_email",
                "skip_if": {"event": "reply_received"},
                "delay_days": 0,
                "deleted_at": None,
            },
            {
                "id": "step-3",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "step_order": 3,
                "channel": "linkedin",
                "provider_id": "prov-linkedin",
                "action_type": "send_connection_request",
                "delay_days": 1,
                "deleted_at": None,
            },
        ],
        "campaign_lead_progress": [
            {
                "id": "prog-1",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "company_campaign_lead_id": "lead-1",
                "current_step_id": "step-2",
                "current_step_order": 2,
                "step_status": "pending",
                "next_execute_at": (now - timedelta(minutes=1)).isoformat(),
                "attempts": 0,
                "updated_at": now.isoformat(),
            }
        ],
        "campaign_lead_provider_ids": [],
        "providers": [
            {"id": "prov-email", "slug": "emailbison"},
            {"id": "prov-linkedin", "slug": "heyreach"},
        ],
        "company_campaign_messages": messages,
        "campaign_events": [],
    }


def test_orchestrator_skips_step_when_skip_if_is_met(monkeypatch):
    fake_db = FakeSupabase(_base_tables(with_inbound_reply=True))
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(conditions, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("execute_step must not run for skipped step")),
    )

    result = engine.run_orchestrator_tick(batch_size=10, dry_run=False)
    assert result.leads_processed == 1
    assert result.steps_executed == 0

    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["current_step_id"] == "step-3"
    assert progress["current_step_order"] == 3
    assert progress["step_status"] == "pending"


def test_orchestrator_executes_step_when_skip_if_not_met(monkeypatch):
    fake_db = FakeSupabase(_base_tables(with_inbound_reply=False))
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(conditions, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=True,
            provider_slug="emailbison",
            action_type="send_email",
            raw_response={"id": "msg-123"},
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=10, dry_run=False)
    assert result.leads_processed == 1
    assert result.steps_executed == 1
    assert result.steps_succeeded == 1

    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["current_step_id"] == "step-3"
    assert progress["step_status"] == "pending"


def test_skipped_step_is_written_to_campaign_events(monkeypatch):
    fake_db = FakeSupabase(_base_tables(with_inbound_reply=True))
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(conditions, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("execute_step must not run for skipped step")),
    )

    engine.run_orchestrator_tick(batch_size=10, dry_run=False)
    events = fake_db.tables["campaign_events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "step_send_email_skipped"
    assert events[0]["company_campaign_lead_id"] == "lead-1"
