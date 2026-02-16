from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.main import app
from src.routers import internal_reconciliation as reconciliation_router


def _fake_reconciliation_response():
    now = datetime.now(timezone.utc)
    return reconciliation_router.ReconciliationRunResponse(
        dry_run=True,
        started_at=now,
        finished_at=now,
        providers=[],
    )


def test_reconciliation_internal_endpoint_requires_super_admin():
    client = TestClient(app)
    response = client.post("/api/internal/reconciliation/campaigns-leads", json={"dry_run": True})
    assert response.status_code == 401


def test_scheduler_endpoint_rejects_missing_secret_when_configured(monkeypatch):
    monkeypatch.setattr(reconciliation_router.settings, "internal_scheduler_secret", "sched-secret")
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/run-scheduled",
        json={"dry_run": True},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid scheduler secret"


def test_scheduler_endpoint_rejects_invalid_secret(monkeypatch):
    monkeypatch.setattr(reconciliation_router.settings, "internal_scheduler_secret", "sched-secret")
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/run-scheduled",
        json={"dry_run": True},
        headers={"X-Internal-Scheduler-Secret": "wrong-secret"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid scheduler secret"


def test_scheduler_endpoint_returns_503_when_scheduler_secret_not_configured(monkeypatch):
    monkeypatch.setattr(reconciliation_router.settings, "internal_scheduler_secret", None)
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/run-scheduled",
        json={"dry_run": True},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "internal scheduler secret is not configured"


def test_scheduler_endpoint_accepts_valid_secret_without_user_auth(monkeypatch):
    monkeypatch.setattr(reconciliation_router.settings, "internal_scheduler_secret", "sched-secret")
    monkeypatch.setattr(reconciliation_router, "_run_reconciliation", lambda data, request_id=None: _fake_reconciliation_response())
    client = TestClient(app)

    response = client.post(
        "/api/internal/reconciliation/run-scheduled",
        json={"dry_run": True},
        headers={"X-Internal-Scheduler-Secret": "sched-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["providers"] == []
