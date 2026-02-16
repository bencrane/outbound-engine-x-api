from __future__ import annotations

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
