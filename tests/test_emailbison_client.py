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
