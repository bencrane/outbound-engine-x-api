from datetime import datetime, timedelta, timezone

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


def _ts(delta_days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat()


def _set_auth(auth: AuthContext):
    async def _override():
        return auth
    app.dependency_overrides[get_current_auth] = _override


def _clear():
    app.dependency_overrides.clear()


def test_campaigns_analytics_dashboard_company_scoped(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "name": "Campaign 1",
                    "status": "ACTIVE",
                    "created_by_user_id": "u-1",
                    "created_at": _ts(-3),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "status": "active", "updated_at": _ts(-2), "deleted_at": None},
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "status": "paused", "updated_at": _ts(-2), "deleted_at": None},
            ],
            "company_campaign_messages": [
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "outbound", "sent_at": _ts(-2), "updated_at": _ts(-2), "deleted_at": None},
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "inbound", "sent_at": _ts(-1), "updated_at": _ts(-1), "deleted_at": None},
            ],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/analytics/campaigns")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["campaign_id"] == "cmp-1"
    assert body[0]["leads_total"] == 2
    assert body[0]["replies_total"] == 1
    assert body[0]["outbound_messages_total"] == 1
    assert body[0]["reply_rate"] == 100.0

    _clear()


def test_campaigns_analytics_dashboard_respects_date_filter(monkeypatch):
    old_ts = _ts(-10)
    new_ts = _ts(-1)
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "name": "Campaign 1",
                    "status": "ACTIVE",
                    "created_by_user_id": "u-1",
                    "created_at": _ts(-15),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [],
            "company_campaign_messages": [
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "outbound", "sent_at": old_ts, "updated_at": old_ts, "deleted_at": None},
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "outbound", "sent_at": new_ts, "updated_at": new_ts, "deleted_at": None},
            ],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get(
        "/api/analytics/campaigns",
        params={"company_id": "c-1", "from_ts": _ts(-2)},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["outbound_messages_total"] == 1

    _clear()


def test_clients_analytics_rollup_for_org_admin(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "name": "Campaign 1",
                    "status": "ACTIVE",
                    "created_by_user_id": "u-1",
                    "created_at": _ts(-3),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                },
                {
                    "id": "cmp-2",
                    "org_id": "org-1",
                    "company_id": "c-2",
                    "name": "Campaign 2",
                    "status": "PAUSED",
                    "created_by_user_id": "u-2",
                    "created_at": _ts(-4),
                    "updated_at": _ts(-2),
                    "deleted_at": None,
                },
            ],
            "company_campaign_leads": [
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "status": "active", "updated_at": _ts(-2), "deleted_at": None},
                {"org_id": "org-1", "company_campaign_id": "cmp-2", "status": "paused", "updated_at": _ts(-2), "deleted_at": None},
                {"org_id": "org-1", "company_campaign_id": "cmp-2", "status": "active", "updated_at": _ts(-1), "deleted_at": None},
            ],
            "company_campaign_messages": [
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "outbound", "sent_at": _ts(-2), "updated_at": _ts(-2), "deleted_at": None},
                {"org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "inbound", "sent_at": _ts(-1), "updated_at": _ts(-1), "deleted_at": None},
                {"org_id": "org-1", "company_campaign_id": "cmp-2", "direction": "outbound", "sent_at": _ts(-1), "updated_at": _ts(-1), "deleted_at": None},
            ],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/analytics/clients")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    c1 = next(row for row in rows if row["company_id"] == "c-1")
    c2 = next(row for row in rows if row["company_id"] == "c-2")
    assert c1["campaigns_total"] == 1
    assert c1["leads_total"] == 1
    assert c1["replies_total"] == 1
    assert c2["campaigns_total"] == 1
    assert c2["leads_total"] == 2
    assert c2["outbound_messages_total"] == 1

    _clear()


def test_reliability_analytics_rollup(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "webhook_events": [
                {
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_slug": "smartlead",
                    "status": "processed",
                    "replay_count": 0,
                    "last_error": None,
                    "created_at": _ts(-1),
                },
                {
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_slug": "smartlead",
                    "status": "replayed",
                    "replay_count": 2,
                    "last_error": "transient timeout",
                    "created_at": _ts(-1),
                },
                {
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_slug": "heyreach",
                    "status": "replayed",
                    "replay_count": 1,
                    "last_error": None,
                    "created_at": _ts(-1),
                },
            ],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/analytics/reliability?company_id=c-1")
    assert response.status_code == 200
    body = response.json()
    assert body["events_total"] == 3
    assert body["replayed_events_total"] == 2
    assert body["replay_count_total"] == 3
    assert body["errors_total"] == 1
    assert len(body["by_provider"]) == 2
    smartlead = next(item for item in body["by_provider"] if item["provider_slug"] == "smartlead")
    assert smartlead["events_total"] == 2
    assert smartlead["errors_total"] == 1

    _clear()


def test_message_sync_health_lists_campaign_sync_state(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "name": "Campaign 1",
                    "status": "ACTIVE",
                    "provider_id": "prov-smartlead",
                    "message_sync_status": "success",
                    "last_message_sync_at": _ts(-1),
                    "last_message_sync_error": None,
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                },
                {
                    "id": "cmp-2",
                    "org_id": "org-1",
                    "company_id": "c-2",
                    "name": "Campaign 2",
                    "status": "ACTIVE",
                    "provider_id": "prov-heyreach",
                    "message_sync_status": "partial_error",
                    "last_message_sync_at": _ts(-1),
                    "last_message_sync_error": "lead messages fetch failed [transient]",
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                },
            ],
            "company_campaign_leads": [
                {"id": "l-1", "org_id": "org-1", "company_campaign_id": "cmp-1", "deleted_at": None},
                {"id": "l-2", "org_id": "org-1", "company_campaign_id": "cmp-2", "deleted_at": None},
            ],
            "company_campaign_messages": [
                {"id": "m-1", "org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "inbound", "deleted_at": None},
                {"id": "m-2", "org_id": "org-1", "company_campaign_id": "cmp-1", "direction": "outbound", "deleted_at": None},
                {"id": "m-3", "org_id": "org-1", "company_campaign_id": "cmp-2", "direction": "outbound", "deleted_at": None},
            ],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/analytics/message-sync-health?message_sync_status=success")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["campaign_id"] == "cmp-1"
    assert rows[0]["messages_total"] == 2
    assert rows[0]["inbound_total"] == 1
    assert rows[0]["outbound_total"] == 1

    _clear()


def test_campaign_sequence_step_performance(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-1",
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "name": "Campaign 1",
                    "status": "ACTIVE",
                    "created_by_user_id": "u-1",
                    "created_at": _ts(-10),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [],
            "company_campaign_messages": [
                # lead A: step 1 outbound then inbound
                {
                    "id": "m-1",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "company_campaign_lead_id": "lead-a",
                    "external_lead_id": "ext-a",
                    "direction": "outbound",
                    "sequence_step_number": 1,
                    "sent_at": _ts(-3),
                    "updated_at": _ts(-3),
                    "deleted_at": None,
                },
                {
                    "id": "m-2",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "company_campaign_lead_id": "lead-a",
                    "external_lead_id": "ext-a",
                    "direction": "inbound",
                    "sequence_step_number": None,
                    "sent_at": _ts(-2),
                    "updated_at": _ts(-2),
                    "deleted_at": None,
                },
                # lead B: step 1 outbound then step 2 outbound then inbound
                {
                    "id": "m-3",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "company_campaign_lead_id": "lead-b",
                    "external_lead_id": "ext-b",
                    "direction": "outbound",
                    "sequence_step_number": 1,
                    "sent_at": _ts(-5),
                    "updated_at": _ts(-5),
                    "deleted_at": None,
                },
                {
                    "id": "m-4",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "company_campaign_lead_id": "lead-b",
                    "external_lead_id": "ext-b",
                    "direction": "outbound",
                    "sequence_step_number": 2,
                    "sent_at": _ts(-4),
                    "updated_at": _ts(-4),
                    "deleted_at": None,
                },
                {
                    "id": "m-5",
                    "org_id": "org-1",
                    "company_campaign_id": "cmp-1",
                    "company_campaign_lead_id": "lead-b",
                    "external_lead_id": "ext-b",
                    "direction": "inbound",
                    "sequence_step_number": None,
                    "sent_at": _ts(-1),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                },
            ],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/analytics/campaigns/cmp-1/sequence-steps")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    step1 = next(row for row in rows if row["sequence_step_number"] == 1)
    step2 = next(row for row in rows if row["sequence_step_number"] == 2)
    assert step1["outbound_messages_total"] == 2
    assert step1["replies_total"] == 1
    assert step1["reply_rate"] == 50.0
    assert step2["outbound_messages_total"] == 1
    assert step2["replies_total"] == 1
    assert step2["reply_rate"] == 100.0

    _clear()


def test_org_level_non_admin_cannot_access_org_wide_analytics(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-2", role="user", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/analytics/campaigns")
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin role required"

    _clear()


def test_company_scoped_user_cannot_query_different_company_analytics(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/analytics/reliability?company_id=c-2")
    assert response.status_code == 404
    assert response.json()["detail"] == "Company not found"

    _clear()


def test_company_scoped_user_cannot_access_other_company_sequence_step_analytics(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [
                {
                    "id": "cmp-2",
                    "org_id": "org-1",
                    "company_id": "c-2",
                    "name": "Other Company Campaign",
                    "status": "ACTIVE",
                    "created_by_user_id": "u-9",
                    "created_at": _ts(-2),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                }
            ],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/analytics/campaigns/cmp-2/sequence-steps")
    assert response.status_code == 404
    assert response.json()["detail"] == "Campaign not found"

    _clear()


def test_direct_mail_analytics_happy_path(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "company_direct_mail_pieces": [
                {
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "piece_type": "postcard",
                    "status": "delivered",
                    "created_at": _ts(-2),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                },
                {
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "piece_type": "letter",
                    "status": "failed",
                    "created_at": _ts(-1),
                    "updated_at": _ts(-1),
                    "deleted_at": None,
                },
            ],
            "webhook_events": [
                {
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_slug": "lob",
                    "event_type": "piece.delivered",
                    "status": "processed",
                    "last_error": None,
                    "payload": {"_ingestion": {"signature_reason": "verified"}},
                    "created_at": _ts(-1),
                },
                {
                    "org_id": "org-1",
                    "company_id": "c-1",
                    "provider_slug": "lob",
                    "event_type": "piece.failed",
                    "status": "dead_letter",
                    "last_error": "provider timeout",
                    "payload": {"_dead_letter": {"reason": "projection_failure", "retryable": True}},
                    "created_at": _ts(-1),
                },
            ],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get("/api/analytics/direct-mail", params={"company_id": "c-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["org_id"] == "org-1"
    assert body["company_id"] == "c-1"
    assert body["total_pieces"] == 2
    assert any(item["piece_type"] == "postcard" and item["status"] == "delivered" for item in body["volume_by_type_status"])
    assert any(item["stage"] == "delivered" and item["count"] >= 1 for item in body["delivery_funnel"])
    assert any(item["reason"] == "projection_failure" for item in body["failure_reason_breakdown"])
    assert len(body["daily_trends"]) >= 1

    _clear()


def test_direct_mail_analytics_empty_dataset(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "company_direct_mail_pieces": [],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.get("/api/analytics/direct-mail")
    assert response.status_code == 200
    body = response.json()
    assert body["company_id"] == "c-1"
    assert body["total_pieces"] == 0
    assert body["volume_by_type_status"] == []
    assert body["failure_reason_breakdown"] == []

    _clear()


def test_direct_mail_analytics_invalid_filters(monkeypatch):
    fake_db = FakeSupabase(
        {
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "company_direct_mail_pieces": [],
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))

    client = TestClient(app)
    response = client.get(
        "/api/analytics/direct-mail",
        params={
            "from_ts": "2026-02-02T00:00:00+00:00",
            "to_ts": "2026-02-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["type"] == "invalid_filter"

    conflict = client.get("/api/analytics/direct-mail", params={"all_companies": "true", "company_id": "c-1"})
    assert conflict.status_code == 400
    assert conflict.json()["detail"]["type"] == "invalid_filter"

    _clear()


def test_direct_mail_analytics_max_rows_and_pagination(monkeypatch):
    piece_rows = [
        {
            "org_id": "org-1",
            "company_id": "c-1",
            "piece_type": "postcard",
            "status": "queued",
            "created_at": _ts(-1),
            "updated_at": _ts(-1),
            "deleted_at": None,
        },
        {
            "org_id": "org-1",
            "company_id": "c-1",
            "piece_type": "letter",
            "status": "delivered",
            "created_at": _ts(-1),
            "updated_at": _ts(-1),
            "deleted_at": None,
        },
    ]
    fake_db = FakeSupabase(
        {
            "company_campaigns": [],
            "company_campaign_leads": [],
            "company_campaign_messages": [],
            "company_direct_mail_pieces": piece_rows,
            "webhook_events": [],
        }
    )
    monkeypatch.setattr(analytics_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-admin", role="admin", company_id=None, auth_method="api_token"))
    client = TestClient(app)

    too_many = client.get("/api/analytics/direct-mail", params={"company_id": "c-1", "max_rows": 1})
    assert too_many.status_code == 400
    assert too_many.json()["detail"]["type"] == "invalid_filter"

    paged = client.get("/api/analytics/direct-mail", params={"company_id": "c-1", "limit": 1, "offset": 1})
    assert paged.status_code == 200
    assert len(paged.json()["volume_by_type_status"]) == 1
    _clear()
