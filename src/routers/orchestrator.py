from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from src.auth import SuperAdminContext, get_current_super_admin
from src.config import settings
from src.observability import incr_metric, log_event
from src.orchestrator.engine import run_orchestrator_tick


router = APIRouter(prefix="/api/internal/orchestrator", tags=["internal-orchestrator"])


class OrchestratorTickRequest(BaseModel):
    batch_size: int | None = None
    dry_run: bool = False


class OrchestratorTickResponse(BaseModel):
    leads_processed: int
    steps_executed: int
    steps_succeeded: int
    steps_retried: int
    steps_failed: int
    leads_completed: int
    dry_run: bool
    errors: list[str]
    enabled: bool


def _disabled_response(*, dry_run: bool) -> OrchestratorTickResponse:
    return OrchestratorTickResponse(
        leads_processed=0,
        steps_executed=0,
        steps_succeeded=0,
        steps_retried=0,
        steps_failed=0,
        leads_completed=0,
        dry_run=dry_run,
        errors=[],
        enabled=False,
    )


def _run_tick(data: OrchestratorTickRequest) -> OrchestratorTickResponse:
    if not settings.orchestrator_tick_enabled:
        return _disabled_response(dry_run=data.dry_run)

    tick_result = run_orchestrator_tick(
        batch_size=data.batch_size or settings.orchestrator_tick_batch_size,
        dry_run=data.dry_run,
    )
    return OrchestratorTickResponse(
        leads_processed=tick_result.leads_processed,
        steps_executed=tick_result.steps_executed,
        steps_succeeded=tick_result.steps_succeeded,
        steps_retried=tick_result.steps_retried,
        steps_failed=tick_result.steps_failed,
        leads_completed=tick_result.leads_completed,
        dry_run=tick_result.dry_run,
        errors=tick_result.errors,
        enabled=True,
    )


@router.post("/tick", response_model=OrchestratorTickResponse)
async def run_orchestrator_tick_scheduled(
    data: OrchestratorTickRequest,
    x_internal_scheduler_secret: str | None = Header(default=None),
):
    configured_secret = settings.internal_scheduler_secret
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal scheduler secret is not configured",
        )
    if not x_internal_scheduler_secret or not hmac.compare_digest(
        x_internal_scheduler_secret,
        configured_secret,
    ):
        incr_metric("orchestrator.scheduled.auth_failed")
        log_event("orchestrator_scheduled_auth_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid scheduler secret",
        )
    incr_metric("orchestrator.scheduled.auth_succeeded")
    return _run_tick(data)


@router.post("/tick-manual", response_model=OrchestratorTickResponse)
async def run_orchestrator_tick_manual(
    data: OrchestratorTickRequest,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    return _run_tick(data)
