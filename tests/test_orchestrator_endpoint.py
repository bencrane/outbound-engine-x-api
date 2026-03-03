from __future__ import annotations

from fastapi.testclient import TestClient

from src.auth.context import SuperAdminContext
from src.auth.dependencies import get_current_super_admin
from src.main import app
from src.orchestrator.engine import OrchestratorTickResult
from src.routers import orchestrator as orchestrator_router


def _set_super_admin():
    async def _override():
        return SuperAdminContext(super_admin_id="sa-1", email="sa@example.com")

    app.dependency_overrides[get_current_super_admin] = _override


def _clear():
    app.dependency_overrides.clear()


def test_tick_missing_scheduler_secret_returns_401(monkeypatch):
    monkeypatch.setattr(orchestrator_router.settings, "internal_scheduler_secret", "sched-secret")
    client = TestClient(app)

    response = client.post("/api/internal/orchestrator/tick", json={"dry_run": True})
    assert response.status_code == 401


def test_tick_invalid_scheduler_secret_returns_401(monkeypatch):
    monkeypatch.setattr(orchestrator_router.settings, "internal_scheduler_secret", "sched-secret")
    client = TestClient(app)

    response = client.post(
        "/api/internal/orchestrator/tick",
        json={"dry_run": True},
        headers={"X-Internal-Scheduler-Secret": "wrong-secret"},
    )
    assert response.status_code == 401


def test_tick_scheduler_secret_not_configured_returns_503(monkeypatch):
    monkeypatch.setattr(orchestrator_router.settings, "internal_scheduler_secret", None)
    client = TestClient(app)

    response = client.post(
        "/api/internal/orchestrator/tick",
        json={"dry_run": True},
        headers={"X-Internal-Scheduler-Secret": "anything"},
    )
    assert response.status_code == 503


def test_tick_disabled_returns_enabled_false(monkeypatch):
    monkeypatch.setattr(orchestrator_router.settings, "internal_scheduler_secret", "sched-secret")
    monkeypatch.setattr(orchestrator_router.settings, "orchestrator_tick_enabled", False)
    client = TestClient(app)

    response = client.post(
        "/api/internal/orchestrator/tick",
        json={"dry_run": True},
        headers={"X-Internal-Scheduler-Secret": "sched-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["leads_processed"] == 0


def test_tick_happy_path_returns_result(monkeypatch):
    monkeypatch.setattr(orchestrator_router.settings, "internal_scheduler_secret", "sched-secret")
    monkeypatch.setattr(orchestrator_router.settings, "orchestrator_tick_enabled", True)
    monkeypatch.setattr(orchestrator_router.settings, "orchestrator_tick_batch_size", 50)
    monkeypatch.setattr(
        orchestrator_router,
        "run_orchestrator_tick",
        lambda **_kwargs: OrchestratorTickResult(
            leads_processed=2,
            steps_executed=2,
            steps_succeeded=1,
            steps_retried=1,
            steps_failed=0,
            leads_completed=0,
            dry_run=False,
            errors=[],
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/api/internal/orchestrator/tick",
        json={"dry_run": False},
        headers={"X-Internal-Scheduler-Secret": "sched-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["leads_processed"] == 2
    assert body["steps_retried"] == 1


def test_tick_manual_super_admin_works(monkeypatch):
    monkeypatch.setattr(orchestrator_router.settings, "orchestrator_tick_enabled", True)
    monkeypatch.setattr(orchestrator_router.settings, "orchestrator_tick_batch_size", 50)
    monkeypatch.setattr(
        orchestrator_router,
        "run_orchestrator_tick",
        lambda **_kwargs: OrchestratorTickResult(
            leads_processed=1,
            steps_executed=1,
            steps_succeeded=1,
            steps_retried=0,
            steps_failed=0,
            leads_completed=1,
            dry_run=True,
            errors=[],
        ),
    )
    _set_super_admin()
    client = TestClient(app)

    response = client.post("/api/internal/orchestrator/tick-manual", json={"dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["leads_completed"] == 1
    _clear()
