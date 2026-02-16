from __future__ import annotations

import json
import logging
from collections import Counter
from threading import Lock
from typing import Any

import httpx


logger = logging.getLogger("outbound_engine_x")

_metrics_lock = Lock()
_metrics_counter: Counter[str] = Counter()


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize(v) for v in value]
    return str(value)


def metric_key(name: str, **labels: Any) -> str:
    if not labels:
        return name
    ordered = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{name}|{ordered}"


def incr_metric(name: str, value: int = 1, **labels: Any) -> None:
    key = metric_key(name, **{k: _normalize(v) for k, v in labels.items()})
    with _metrics_lock:
        _metrics_counter[key] += value


def metrics_snapshot() -> dict[str, int]:
    with _metrics_lock:
        return dict(_metrics_counter)


def reset_metrics() -> None:
    with _metrics_lock:
        _metrics_counter.clear()


def persist_metrics_snapshot(
    *,
    supabase_client: Any,
    source: str,
    request_id: str | None = None,
    reset_after_persist: bool = False,
    export_url: str | None = None,
    export_bearer_token: str | None = None,
    export_timeout_seconds: float = 3.0,
) -> bool:
    snapshot = metrics_snapshot()
    try:
        supabase_client.table("observability_metric_snapshots").insert(
            {
                "source": source,
                "request_id": request_id,
                "counters": snapshot,
            }
        ).execute()
    except Exception as exc:
        log_event(
            "metrics_snapshot_persist_failed",
            level=logging.WARNING,
            request_id=request_id,
            source=source,
            error=str(exc),
        )
        return False

    if export_url:
        headers = {"Content-Type": "application/json"}
        if export_bearer_token:
            headers["Authorization"] = f"Bearer {export_bearer_token}"
        payload = {
            "source": source,
            "request_id": request_id,
            "counters": snapshot,
        }
        try:
            with httpx.Client(timeout=export_timeout_seconds) as client:
                response = client.post(export_url, headers=headers, json=payload)
            if response.status_code >= 400:
                log_event(
                    "metrics_snapshot_export_failed",
                    level=logging.WARNING,
                    request_id=request_id,
                    source=source,
                    export_url=export_url,
                    status_code=response.status_code,
                    response_text=response.text[:200],
                )
            else:
                log_event(
                    "metrics_snapshot_exported",
                    request_id=request_id,
                    source=source,
                    export_url=export_url,
                    status_code=response.status_code,
                )
        except Exception as exc:
            log_event(
                "metrics_snapshot_export_failed",
                level=logging.WARNING,
                request_id=request_id,
                source=source,
                export_url=export_url,
                error=str(exc),
            )

    log_event(
        "metrics_snapshot_persisted",
        request_id=request_id,
        source=source,
        counter_count=len(snapshot),
    )
    if reset_after_persist:
        reset_metrics()
    return True


def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    request_id: str | None = None,
    **fields: Any,
) -> None:
    payload = {"event": event}
    if request_id:
        payload["request_id"] = request_id
    for key, value in fields.items():
        payload[key] = _normalize(value)
    logger.log(level, json.dumps(payload, sort_keys=True))
