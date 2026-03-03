from __future__ import annotations

from src.orchestrator import conditions


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name: str, db: "FakeSupabase"):
        self.table_name = table_name
        self.db = db
        self.filters: list[tuple[str, str, object]] = []
        self.limit_count: int | None = None

    def select(self, _fields: str):
        return self

    def eq(self, key: str, value):
        self.filters.append(("eq", key, value))
        return self

    def is_(self, key: str, value):
        self.filters.append(("is", key, value))
        return self

    def limit(self, count: int):
        self.limit_count = count
        return self

    def _matches(self, row: dict) -> bool:
        for kind, key, value in self.filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "is" and value == "null" and row.get(key) is not None:
                return False
        return True

    def execute(self):
        rows = [dict(row) for row in self.db.tables.get(self.table_name, []) if self._matches(row)]
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def test_skip_if_reply_received_reply_exists_returns_true(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaign_messages": [
                {
                    "id": "msg-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "company_campaign_lead_id": "lead-1",
                    "direction": "inbound",
                    "deleted_at": None,
                }
            ]
        }
    )
    monkeypatch.setattr(conditions, "supabase", fake_db)

    assert (
        conditions.should_skip_step(
            skip_if={"event": "reply_received"},
            lead_id="lead-1",
            campaign_id="cmp-1",
            org_id="org-1",
        )
        is True
    )


def test_skip_if_reply_received_no_reply_returns_false(monkeypatch):
    fake_db = FakeSupabase({"company_campaign_messages": []})
    monkeypatch.setattr(conditions, "supabase", fake_db)

    assert (
        conditions.should_skip_step(
            skip_if={"event": "reply_received"},
            lead_id="lead-1",
            campaign_id="cmp-1",
            org_id="org-1",
        )
        is False
    )


def test_skip_if_lead_status_match_returns_true(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaign_leads": [
                {
                    "id": "lead-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "status": "unsubscribed",
                    "deleted_at": None,
                }
            ]
        }
    )
    monkeypatch.setattr(conditions, "supabase", fake_db)

    assert (
        conditions.should_skip_step(
            skip_if={"lead_status": "unsubscribed"},
            lead_id="lead-1",
            campaign_id="cmp-1",
            org_id="org-1",
        )
        is True
    )


def test_skip_if_lead_status_mismatch_returns_false(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaign_leads": [
                {
                    "id": "lead-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "status": "active",
                    "deleted_at": None,
                }
            ]
        }
    )
    monkeypatch.setattr(conditions, "supabase", fake_db)

    assert (
        conditions.should_skip_step(
            skip_if={"lead_status": "unsubscribed"},
            lead_id="lead-1",
            campaign_id="cmp-1",
            org_id="org-1",
        )
        is False
    )


def test_skip_if_none_returns_false(monkeypatch):
    fake_db = FakeSupabase({})
    monkeypatch.setattr(conditions, "supabase", fake_db)
    assert (
        conditions.should_skip_step(
            skip_if=None,
            lead_id="lead-1",
            campaign_id="cmp-1",
            org_id="org-1",
        )
        is False
    )


def test_skip_if_unrecognized_structure_returns_false(monkeypatch):
    fake_db = FakeSupabase({})
    monkeypatch.setattr(conditions, "supabase", fake_db)
    assert (
        conditions.should_skip_step(
            skip_if={"foo": "bar"},
            lead_id="lead-1",
            campaign_id="cmp-1",
            org_id="org-1",
        )
        is False
    )
