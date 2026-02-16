from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import SuperAdminContext
from src.auth.dependencies import get_current_super_admin
from src.main import app
from src import observability
from src.observability import incr_metric, reset_metrics
from src.routers import super_admin as super_admin_router


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

    def select(self, _fields: str):
        self.operation = "select"
        return self

    def insert(self, payload: dict):
        self.operation = "insert"
        self.insert_payload = payload
        return self

    def eq(self, key: str, value):
        self.filters.append((key, value))
        return self

    def _matches(self, row: dict) -> bool:
        return all(row.get(key) == value for key, value in self.filters)

    def execute(self):
        table = self.db.tables.setdefault(self.table_name, [])
        if self.operation == "insert":
            row = dict(self.insert_payload or {})
            row.setdefault("id", f"{self.table_name}-{len(table)+1}")
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            table.append(row)
            return FakeResponse([row])
        rows = [dict(row) for row in table if self._matches(row)]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self):
        self.tables = {"observability_metric_snapshots": []}

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def _set_super_admin_override():
    async def _override():
        return SuperAdminContext(super_admin_id="sa-1", email="admin@example.com")

    app.dependency_overrides[get_current_super_admin] = _override


def _clear_overrides():
    app.dependency_overrides.clear()


def test_metrics_snapshot_flush_and_list(monkeypatch):
    reset_metrics()
    incr_metric("webhook.events.processed", provider_slug="smartlead")
    fake_db = FakeSupabase()
    monkeypatch.setattr(super_admin_router, "supabase", fake_db)
    _set_super_admin_override()
    client = TestClient(app)

    flush_resp = client.post(
        "/api/super-admin/observability/metrics-snapshots/flush",
        json={"source": "test_flush", "reset_after_persist": False},
    )
    assert flush_resp.status_code == 200
    flush_body = flush_resp.json()
    assert flush_body["persisted"] is True
    assert flush_body["source"] == "test_flush"
    assert flush_body["counter_count"] >= 1

    list_resp = client.get("/api/super-admin/observability/metrics-snapshots?limit=10")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "test_flush"
    assert isinstance(rows[0]["counters"], dict)

    _clear_overrides()
    reset_metrics()


def test_metrics_snapshot_endpoints_require_super_admin():
    client = TestClient(app)
    list_resp = client.get("/api/super-admin/observability/metrics-snapshots")
    flush_resp = client.post("/api/super-admin/observability/metrics-snapshots/flush", json={})
    assert list_resp.status_code == 401
    assert flush_resp.status_code == 401


def test_metrics_snapshot_flush_exports_when_sink_configured(monkeypatch):
    class _FakeHttpResponse:
        status_code = 202
        text = "accepted"

    exported = []

    class _FakeHttpClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            exported.append(
                {
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "timeout": self.timeout,
                }
            )
            return _FakeHttpResponse()

    reset_metrics()
    incr_metric("webhook.events.processed", provider_slug="smartlead")
    fake_db = FakeSupabase()
    monkeypatch.setattr(super_admin_router, "supabase", fake_db)
    monkeypatch.setattr(super_admin_router.settings, "observability_export_url", "https://example.com/metrics")
    monkeypatch.setattr(super_admin_router.settings, "observability_export_bearer_token", "tok-123")
    monkeypatch.setattr(super_admin_router.settings, "observability_export_timeout_seconds", 2.5)
    monkeypatch.setattr(observability.httpx, "Client", _FakeHttpClient)
    _set_super_admin_override()
    client = TestClient(app)

    response = client.post(
        "/api/super-admin/observability/metrics-snapshots/flush",
        json={"source": "test_export", "reset_after_persist": False},
    )
    assert response.status_code == 200
    assert response.json()["persisted"] is True
    assert len(exported) == 1
    assert exported[0]["url"] == "https://example.com/metrics"
    assert exported[0]["headers"]["Authorization"] == "Bearer tok-123"
    assert exported[0]["json"]["source"] == "test_export"
    assert exported[0]["timeout"] == 2.5

    _clear_overrides()
    reset_metrics()


def test_metrics_snapshot_flush_succeeds_when_export_fails(monkeypatch):
    class _FailingHttpClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            raise RuntimeError("sink unavailable")

    reset_metrics()
    incr_metric("webhook.events.processed", provider_slug="heyreach")
    fake_db = FakeSupabase()
    monkeypatch.setattr(super_admin_router, "supabase", fake_db)
    monkeypatch.setattr(super_admin_router.settings, "observability_export_url", "https://example.com/metrics")
    monkeypatch.setattr(super_admin_router.settings, "observability_export_bearer_token", None)
    monkeypatch.setattr(observability.httpx, "Client", _FailingHttpClient)
    _set_super_admin_override()
    client = TestClient(app)

    response = client.post(
        "/api/super-admin/observability/metrics-snapshots/flush",
        json={"source": "test_export_failure", "reset_after_persist": False},
    )
    assert response.status_code == 200
    assert response.json()["persisted"] is True
    assert len(fake_db.tables["observability_metric_snapshots"]) == 1
    assert fake_db.tables["observability_metric_snapshots"][0]["source"] == "test_export_failure"

    _clear_overrides()
    reset_metrics()
