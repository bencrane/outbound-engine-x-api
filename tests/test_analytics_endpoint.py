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
