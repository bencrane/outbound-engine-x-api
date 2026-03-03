from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
            self.db.write_count += 1
            row = dict(self.insert_payload or {})
            row.setdefault("id", f"{self.table_name}-{len(table)+1}")
            row.setdefault("created_at", _ts())
            row.setdefault("updated_at", _ts())
            table.append(row)
            return FakeResponse([dict(row)])

        if self.operation == "update":
            self.db.write_count += 1
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
        self.write_count = 0

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _base_tables():
    now = datetime.now(timezone.utc)
    return {
        "company_campaigns": [
            {
                "id": "cmp-1",
                "org_id": "org-1",
                "deleted_at": None,
            }
        ],
        "company_campaign_leads": [
            {
                "id": "lead-1",
                "company_campaign_id": "cmp-1",
                "email": "lead@example.com",
                "first_name": "Ada",
                "last_name": "Lovelace",
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
                "delay_days": 0,
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
                "delay_days": 2,
                "deleted_at": None,
            },
            {
                "id": "step-3",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "step_order": 3,
                "channel": "email",
                "provider_id": "prov-email",
                "action_type": "send_email",
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
                "current_step_id": "step-1",
                "current_step_order": 1,
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
    }


def test_happy_path_lead_advances_to_next_step(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=True,
            provider_slug="emailbison",
            action_type="send_email",
            external_id="ext-email-1",
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=50, dry_run=False)
    assert result.leads_processed == 1
    assert result.steps_executed == 1
    assert result.steps_succeeded == 1

    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["current_step_id"] == "step-2"
    assert progress["current_step_order"] == 2
    assert progress["step_status"] == "pending"
    assert progress["attempts"] == 0
    next_execute_at = _parse_ts(progress["next_execute_at"])
    assert next_execute_at is not None
    assert next_execute_at > datetime.now(timezone.utc) + timedelta(days=1, hours=23)

    assert len(fake_db.tables["campaign_lead_provider_ids"]) == 1
    assert fake_db.tables["campaign_lead_provider_ids"][0]["external_id"] == "ext-email-1"


def test_lead_completes_all_steps(monkeypatch):
    tables = _base_tables()
    tables["campaign_lead_progress"][0]["current_step_id"] = "step-3"
    tables["campaign_lead_progress"][0]["current_step_order"] = 3
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=True,
            provider_slug="emailbison",
            action_type="send_email",
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=50, dry_run=False)
    assert result.leads_completed == 1
    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["step_status"] == "completed"
    assert progress.get("completed_at") is not None
    assert progress.get("next_execute_at") is None


def test_retryable_failure_requeues_with_backoff(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=False,
            provider_slug="emailbison",
            action_type="send_email",
            error_message="provider timeout",
            retryable=True,
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=50, dry_run=False)
    assert result.steps_retried == 1
    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["step_status"] == "pending"
    assert progress["attempts"] == 1
    assert progress["last_error"] == "provider timeout"
    assert _parse_ts(progress["next_execute_at"]) > datetime.now(timezone.utc)


def test_non_retryable_failure_marks_failed(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=False,
            provider_slug="emailbison",
            action_type="send_email",
            error_message="invalid payload",
            retryable=False,
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=50, dry_run=False)
    assert result.steps_failed == 1
    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["step_status"] == "failed"
    assert progress["attempts"] == 1
    assert progress["next_execute_at"] is None


def test_max_retries_exceeded_marks_failed(monkeypatch):
    tables = _base_tables()
    tables["campaign_lead_progress"][0]["attempts"] = engine.settings.orchestrator_max_retries - 1
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=False,
            provider_slug="emailbison",
            action_type="send_email",
            error_message="temporary outage",
            retryable=True,
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=50, dry_run=False)
    assert result.steps_failed == 1
    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["step_status"] == "failed"
    assert progress["attempts"] == engine.settings.orchestrator_max_retries


def test_stale_lock_recovery_row_gets_processed(monkeypatch):
    tables = _base_tables()
    stale_ts = datetime.now(timezone.utc) - timedelta(minutes=15)
    tables["campaign_lead_progress"][0]["step_status"] = "executing"
    tables["campaign_lead_progress"][0]["updated_at"] = stale_ts.isoformat()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=True,
            provider_slug="emailbison",
            action_type="send_email",
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=50, dry_run=False)
    assert result.leads_processed == 1
    progress = fake_db.tables["campaign_lead_progress"][0]
    assert progress["step_status"] in {"pending", "completed"}


def test_dry_run_has_no_writes(monkeypatch):
    tables = _base_tables()
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("execute_step should not run during dry-run")),
    )

    result = engine.run_orchestrator_tick(batch_size=50, dry_run=True)
    assert result.leads_processed == 1
    assert result.steps_executed == 0
    assert fake_db.write_count == 0


def test_batch_limit_processes_subset(monkeypatch):
    tables = _base_tables()
    now = datetime.now(timezone.utc)
    tables["campaign_lead_progress"] = []
    for i in range(10):
        tables["company_campaign_leads"].append(
            {
                "id": f"lead-{i+2}",
                "company_campaign_id": "cmp-1",
                "email": f"lead{i}@example.com",
                "deleted_at": None,
            }
        )
        tables["campaign_lead_progress"].append(
            {
                "id": f"prog-{i+1}",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "company_campaign_lead_id": f"lead-{i+2}",
                "current_step_id": "step-1",
                "current_step_order": 1,
                "step_status": "pending",
                "next_execute_at": (now - timedelta(minutes=1)).isoformat(),
                "attempts": 0,
                "updated_at": now.isoformat(),
            }
        )
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(engine, "supabase", fake_db)
    monkeypatch.setattr(
        engine,
        "execute_step",
        lambda **_kwargs: StepExecutionResult(
            success=True,
            provider_slug="emailbison",
            action_type="send_email",
        ),
    )

    result = engine.run_orchestrator_tick(batch_size=3, dry_run=False)
    assert result.leads_processed == 3
    assert result.steps_executed == 3
