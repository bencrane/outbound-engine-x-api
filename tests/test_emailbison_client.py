from __future__ import annotations

import types

from src.providers.emailbison import client as emailbison_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_webhook_resource_paths_exposes_single_internal_id_mapping():
    # Spec uses mixed placeholder names ({id} and {webhook_url_id}).
    # Internal callers pass one webhook_id and rely on helper routing.
    paths = emailbison_client.webhook_resource_paths("123")
    assert paths["read_update_canonical"] == "/api/webhook-url/123"
    assert paths["delete_canonical"] == "/api/webhook-url/123"
    assert paths["delete_alias_trailing_slash"] == "/api/webhook-url/123/"


def test_delete_webhook_tolerates_delete_path_variant(monkeypatch):
    calls: list[str] = []

    def _fake_request_with_retry(**kwargs):
        calls.append(kwargs["url"])
        if kwargs["url"].endswith("/api/webhook-url/123"):
            return _FakeResponse(404, {"error": "not found"})
        return _FakeResponse(200, {"data": {"success": True}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    result = emailbison_client.delete_webhook(
        api_key="k",
        webhook_id="123",
        instance_url="https://x.example",
    )

    assert result["success"] is True
    assert calls == [
        "https://x.example/api/webhook-url/123",
        "https://x.example/api/webhook-url/123/",
    ]


def test_campaign_status_update_routes_active_to_resume_endpoint(monkeypatch):
    calls: list[str] = []

    def _fake_request_with_retry(**kwargs):
        calls.append(kwargs["url"])
        return _FakeResponse(200, {"data": {"id": 1, "status": "Queued"}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    result = emailbison_client.update_campaign_status(
        api_key="k",
        campaign_id="77",
        status_value="ACTIVE",
        instance_url="https://x.example",
    )

    assert result["status"] == "Queued"
    assert calls == ["https://x.example/api/campaigns/77/resume"]


def test_campaign_status_update_routes_paused_to_pause_endpoint(monkeypatch):
    calls: list[str] = []

    def _fake_request_with_retry(**kwargs):
        calls.append(kwargs["url"])
        return _FakeResponse(200, {"data": {"id": 1, "status": "Paused"}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    result = emailbison_client.update_campaign_status(
        api_key="k",
        campaign_id="77",
        status_value="PAUSED",
        instance_url="https://x.example",
    )

    assert result["status"] == "Paused"
    assert calls == ["https://x.example/api/campaigns/77/pause"]


def test_campaign_status_update_routes_stopped_to_archive_endpoint(monkeypatch):
    calls: list[str] = []

    def _fake_request_with_retry(**kwargs):
        calls.append(kwargs["url"])
        return _FakeResponse(200, {"data": {"id": 1, "status": "Archived"}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    result = emailbison_client.update_campaign_status(
        api_key="k",
        campaign_id="77",
        status_value="STOPPED",
        instance_url="https://x.example",
    )

    assert result["status"] == "Archived"
    assert calls == ["https://x.example/api/campaigns/77/archive"]


def test_campaign_status_update_rejects_unsupported_transition():
    try:
        emailbison_client.update_campaign_status(
            api_key="k",
            campaign_id="77",
            status_value="DRAFTED",
            instance_url="https://x.example",
        )
    except emailbison_client.EmailBisonProviderError as exc:
        assert "Unsupported EmailBison campaign status transition requested" in str(exc)
    else:
        raise AssertionError("Expected EmailBisonProviderError for unsupported status")


def test_create_leads_bulk_uses_multiple_endpoint(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        return _FakeResponse(201, {"data": [{"id": 1, "email": "a@example.com"}]})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    result = emailbison_client.create_leads_bulk(
        api_key="k",
        leads=[{"first_name": "A", "last_name": "One", "email": "a@example.com"}],
        instance_url="https://x.example",
    )

    assert result == [{"id": 1, "email": "a@example.com"}]
    assert calls == [
        (
            "POST",
            "https://x.example/api/leads/multiple",
            {"leads": [{"first_name": "A", "last_name": "One", "email": "a@example.com"}]},
        )
    ]


def test_unsubscribe_lead_uses_unsubscribe_endpoint(monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"]))
        return _FakeResponse(200, {"data": {"id": 777, "status": "unsubscribed"}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    result = emailbison_client.unsubscribe_lead(
        api_key="k",
        lead_id=777,
        instance_url="https://x.example",
    )

    assert result["status"] == "unsubscribed"
    assert calls == [("PATCH", "https://x.example/api/leads/777/unsubscribe")]


def test_update_lead_status_uses_status_endpoint(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        return _FakeResponse(200, {"data": {"id": 778, "status": "inactive"}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    result = emailbison_client.update_lead_status(
        api_key="k",
        lead_id=778,
        status_value="inactive",
        instance_url="https://x.example",
    )

    assert result["status"] == "inactive"
    assert calls == [
        ("PATCH", "https://x.example/api/leads/778/update-status", {"status": "inactive"})
    ]


def test_get_and_create_campaign_sequence_steps_use_sequence_endpoint(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["method"] == "GET":
            return _FakeResponse(200, {"data": [{"order": 1}]})
        return _FakeResponse(200, {"data": {"id": 10, "sequence_steps": [{"order": 1}]}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    got = emailbison_client.get_campaign_sequence_steps(
        api_key="k",
        campaign_id=22,
        instance_url="https://x.example",
    )
    created = emailbison_client.create_campaign_sequence_steps(
        api_key="k",
        campaign_id=22,
        title="Seq",
        sequence_steps=[{"email_subject": "Hello", "email_body": "Body", "wait_in_days": 0}],
        instance_url="https://x.example",
    )

    assert got == [{"order": 1}]
    assert created["id"] == 10
    assert calls[0] == ("GET", "https://x.example/api/campaigns/22/sequence-steps", None)
    assert calls[1][0] == "POST"
    assert calls[1][1] == "https://x.example/api/campaigns/22/sequence-steps"


def test_get_and_create_campaign_schedule_use_schedule_endpoint(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["method"] == "GET":
            return _FakeResponse(200, {"data": {"timezone": "America/New_York"}})
        return _FakeResponse(200, {"data": {"timezone": "America/New_York", "monday": True}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    got = emailbison_client.get_campaign_schedule(
        api_key="k",
        campaign_id=99,
        instance_url="https://x.example",
    )
    created = emailbison_client.create_campaign_schedule(
        api_key="k",
        campaign_id=99,
        schedule={"monday": True},
        instance_url="https://x.example",
    )

    assert got["timezone"] == "America/New_York"
    assert created["monday"] is True
    assert calls[0] == ("GET", "https://x.example/api/campaigns/99/schedule", None)
    assert calls[1] == ("POST", "https://x.example/api/campaigns/99/schedule", {"monday": True})


def test_registry_covers_all_public_client_methods():
    excluded = {"webhook_resource_paths"}
    public_callables = {
        name
        for name, value in vars(emailbison_client).items()
        if isinstance(value, types.FunctionType) and not name.startswith("_") and name not in excluded
    }
    registered = set(emailbison_client.EMAILBISON_IMPLEMENTED_ENDPOINT_REGISTRY.keys())
    assert public_callables == registered
