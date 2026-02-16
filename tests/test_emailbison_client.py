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


def test_get_reply_and_thread_endpoints(monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"]))
        if kwargs["url"].endswith("/conversation-thread"):
            return _FakeResponse(200, {"data": {"current_reply": {"id": 7}}})
        return _FakeResponse(200, {"data": {"id": 7, "subject": "Re: hello"}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    reply = emailbison_client.get_reply(
        api_key="k",
        reply_id=7,
        instance_url="https://x.example",
    )
    thread = emailbison_client.get_reply_conversation_thread(
        api_key="k",
        reply_id=7,
        instance_url="https://x.example",
    )

    assert reply["id"] == 7
    assert thread["current_reply"]["id"] == 7
    assert calls == [
        ("GET", "https://x.example/api/replies/7"),
        ("GET", "https://x.example/api/replies/7/conversation-thread"),
    ]


def test_list_campaign_replies_uses_campaign_endpoint(monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"]))
        return _FakeResponse(200, {"data": [{"id": 50}]})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    replies = emailbison_client.list_campaign_replies(
        api_key="k",
        campaign_id=90,
        instance_url="https://x.example",
    )

    assert replies == [{"id": 50}]
    assert calls == [("GET", "https://x.example/api/campaigns/90/replies")]


def test_sender_email_get_update_delete_endpoints(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["method"] == "DELETE":
            return _FakeResponse(200, {"data": {"success": True}})
        return _FakeResponse(200, {"data": {"id": 11, "email": "a@example.com"}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    got = emailbison_client.get_sender_email(
        api_key="k",
        sender_email_id=11,
        instance_url="https://x.example",
    )
    updated = emailbison_client.update_sender_email(
        api_key="k",
        sender_email_id=11,
        updates={"name": "Updated"},
        instance_url="https://x.example",
    )
    deleted = emailbison_client.delete_sender_email(
        api_key="k",
        sender_email_id=11,
        instance_url="https://x.example",
    )

    assert got["id"] == 11
    assert updated["id"] == 11
    assert deleted["success"] is True
    assert calls == [
        ("GET", "https://x.example/api/sender-emails/11", None),
        ("PATCH", "https://x.example/api/sender-emails/11", {"name": "Updated"}),
        ("DELETE", "https://x.example/api/sender-emails/11", None),
    ]


def test_warmup_and_mx_check_endpoints(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        return _FakeResponse(200, {"data": {"success": True, "id": 11, "warmup_score": 70}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    _ = emailbison_client.get_sender_email_warmup_details(
        api_key="k",
        sender_email_id=11,
        start_date="2026-02-01",
        end_date="2026-02-15",
        instance_url="https://x.example",
    )
    _ = emailbison_client.enable_warmup_for_sender_emails(
        api_key="k",
        sender_email_ids=[11, 12],
        instance_url="https://x.example",
    )
    _ = emailbison_client.disable_warmup_for_sender_emails(
        api_key="k",
        sender_email_ids=[11, 12],
        instance_url="https://x.example",
    )
    _ = emailbison_client.update_sender_email_daily_warmup_limits(
        api_key="k",
        sender_email_ids=[11, 12],
        daily_limit=8,
        daily_reply_limit="auto",
        instance_url="https://x.example",
    )
    _ = emailbison_client.check_sender_email_mx_records(
        api_key="k",
        sender_email_id=11,
        instance_url="https://x.example",
    )
    _ = emailbison_client.bulk_check_missing_mx_records(
        api_key="k",
        instance_url="https://x.example",
    )

    assert calls[0][0] == "GET"
    assert calls[0][1] == "https://x.example/api/warmup/sender-emails/11"
    assert calls[1] == ("PATCH", "https://x.example/api/warmup/sender-emails/enable", {"sender_email_ids": [11, 12]})
    assert calls[2] == ("PATCH", "https://x.example/api/warmup/sender-emails/disable", {"sender_email_ids": [11, 12]})
    assert calls[3] == (
        "PATCH",
        "https://x.example/api/warmup/sender-emails/update-daily-warmup-limits",
        {"sender_email_ids": [11, 12], "daily_limit": 8, "daily_reply_limit": "auto"},
    )
    assert calls[4] == ("POST", "https://x.example/api/sender-emails/11/check-mx-records", None)
    assert calls[5] == ("POST", "https://x.example/api/sender-emails/bulk-check-missing-mx-records", None)


def test_tags_and_custom_variables_endpoints(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["method"] == "GET" and kwargs["url"].endswith("/api/tags"):
            return _FakeResponse(200, {"data": [{"id": 7, "name": "Important"}]})
        if kwargs["method"] == "GET" and kwargs["url"].endswith("/api/custom-variables"):
            return _FakeResponse(200, {"data": [{"id": 9, "name": "linkedin"}]})
        return _FakeResponse(200, {"data": {"id": 7, "name": "Important", "success": True}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    emailbison_client.list_tags(api_key="k", instance_url="https://x.example")
    emailbison_client.create_tag(api_key="k", name="Important", default=True, instance_url="https://x.example")
    emailbison_client.get_tag(api_key="k", tag_id=7, instance_url="https://x.example")
    emailbison_client.delete_tag(api_key="k", tag_id=7, instance_url="https://x.example")
    emailbison_client.attach_tags_to_campaigns(
        api_key="k",
        tag_ids=[1],
        campaign_ids=[2],
        skip_webhooks=True,
        instance_url="https://x.example",
    )
    emailbison_client.remove_tags_from_campaigns(
        api_key="k",
        tag_ids=[1],
        campaign_ids=[2],
        skip_webhooks=True,
        instance_url="https://x.example",
    )
    emailbison_client.attach_tags_to_leads(
        api_key="k",
        tag_ids=[1],
        lead_ids=[3],
        skip_webhooks=True,
        instance_url="https://x.example",
    )
    emailbison_client.remove_tags_from_leads(
        api_key="k",
        tag_ids=[1],
        lead_ids=[3],
        skip_webhooks=True,
        instance_url="https://x.example",
    )
    emailbison_client.attach_tags_to_sender_emails(
        api_key="k",
        tag_ids=[1],
        sender_email_ids=[4],
        skip_webhooks=True,
        instance_url="https://x.example",
    )
    emailbison_client.remove_tags_from_sender_emails(
        api_key="k",
        tag_ids=[1],
        sender_email_ids=[4],
        skip_webhooks=True,
        instance_url="https://x.example",
    )
    emailbison_client.list_custom_variables(api_key="k", instance_url="https://x.example")
    emailbison_client.create_custom_variable(api_key="k", name="linkedin", instance_url="https://x.example")

    assert calls[0] == ("GET", "https://x.example/api/tags", None)
    assert calls[1] == ("POST", "https://x.example/api/tags", {"name": "Important", "default": True})
    assert calls[2] == ("GET", "https://x.example/api/tags/7", None)
    assert calls[3] == ("DELETE", "https://x.example/api/tags/7", None)
    assert calls[4] == (
        "POST",
        "https://x.example/api/tags/attach-to-campaigns",
        {"tag_ids": [1], "campaign_ids": [2], "skip_webhooks": True},
    )
    assert calls[5] == (
        "POST",
        "https://x.example/api/tags/remove-from-campaigns",
        {"tag_ids": [1], "campaign_ids": [2], "skip_webhooks": True},
    )
    assert calls[10] == ("GET", "https://x.example/api/custom-variables", None)
    assert calls[11] == ("POST", "https://x.example/api/custom-variables", {"name": "linkedin"})


def test_blacklist_endpoints(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["method"] == "GET":
            return _FakeResponse(200, {"data": [{"id": 1}]})
        if kwargs["method"] == "DELETE":
            return _FakeResponse(200, {"data": {"success": True}})
        if kwargs["url"].endswith("/bulk"):
            return _FakeResponse(201, {"data": [{"id": 1}]})
        return _FakeResponse(201, {"data": {"id": 1}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    emailbison_client.list_blacklisted_emails(api_key="k", instance_url="https://x.example")
    emailbison_client.create_blacklisted_email(api_key="k", email="a@example.com", instance_url="https://x.example")
    emailbison_client.bulk_create_blacklisted_emails(
        api_key="k", emails=["a@example.com", "b@example.com"], instance_url="https://x.example"
    )
    emailbison_client.delete_blacklisted_email(api_key="k", blacklisted_email_id=1, instance_url="https://x.example")
    emailbison_client.list_blacklisted_domains(api_key="k", instance_url="https://x.example")
    emailbison_client.create_blacklisted_domain(api_key="k", domain="example.com", instance_url="https://x.example")
    emailbison_client.bulk_create_blacklisted_domains(
        api_key="k", domains=["a.com", "b.com"], instance_url="https://x.example"
    )
    emailbison_client.delete_blacklisted_domain(api_key="k", blacklisted_domain_id=1, instance_url="https://x.example")

    assert calls[0] == ("GET", "https://x.example/api/blacklisted-emails", None)
    assert calls[1] == ("POST", "https://x.example/api/blacklisted-emails", {"email": "a@example.com"})
    assert calls[2] == (
        "POST",
        "https://x.example/api/blacklisted-emails/bulk",
        {"emails": ["a@example.com", "b@example.com"]},
    )
    assert calls[3] == ("DELETE", "https://x.example/api/blacklisted-emails/1", None)
    assert calls[4] == ("GET", "https://x.example/api/blacklisted-domains", None)
    assert calls[5] == ("POST", "https://x.example/api/blacklisted-domains", {"domain": "example.com"})
    assert calls[6] == (
        "POST",
        "https://x.example/api/blacklisted-domains/bulk",
        {"domains": ["a.com", "b.com"]},
    )
    assert calls[7] == ("DELETE", "https://x.example/api/blacklisted-domains/1", None)


def test_workspace_account_settings_and_stats_endpoints(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["url"].endswith("/api/campaign-events/stats"):
            return _FakeResponse(200, {"data": [{"label": "Sent", "dates": [["2026-02-16", 2]]}]})
        return _FakeResponse(200, {"data": {"ok": True}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    emailbison_client.get_workspace_account_details(api_key="k", instance_url="https://x.example")
    emailbison_client.get_workspace_stats(
        api_key="k",
        start_date="2026-02-01",
        end_date="2026-02-16",
        instance_url="https://x.example",
    )
    emailbison_client.get_workspace_master_inbox_settings(api_key="k", instance_url="https://x.example")
    emailbison_client.update_workspace_master_inbox_settings(
        api_key="k",
        updates={"sync_all_emails": True},
        instance_url="https://x.example",
    )
    emailbison_client.get_campaign_events_stats(
        api_key="k",
        start_date="2026-02-01",
        end_date="2026-02-16",
        campaign_ids=[1],
        sender_email_ids=[2],
        instance_url="https://x.example",
    )

    assert calls[0] == ("GET", "https://x.example/api/users", None)
    assert calls[1] == ("GET", "https://x.example/api/workspaces/v1.1/stats", None)
    assert calls[2] == ("GET", "https://x.example/api/workspaces/v1.1/master-inbox-settings", None)
    assert calls[3] == ("PATCH", "https://x.example/api/workspaces/v1.1/master-inbox-settings", {"sync_all_emails": True})
    assert calls[4] == ("GET", "https://x.example/api/campaign-events/stats", None)


def test_contract_status_registry_for_blocked_contract_missing_gaps():
    registry = emailbison_client.EMAILBISON_CONTRACT_STATUS_REGISTRY
    assert registry["custom_variables.update"]["status"] == "blocked_contract_missing"
    assert registry["custom_variables.delete"]["status"] == "blocked_contract_missing"
    assert registry["tags.update"]["status"] == "blocked_contract_missing"
    assert "live user-emailbison api spec output" in registry["custom_variables.update"]["evidence"].lower()


def test_webhook_management_endpoints(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["method"] == "GET" and kwargs["url"].endswith("/api/webhook-url"):
            return _FakeResponse(200, {"data": [{"id": 1, "name": "Hook"}]})
        if kwargs["method"] == "GET" and kwargs["url"].endswith("/api/webhook-events/event-types"):
            return _FakeResponse(200, {"data": [{"id": "email_sent"}]})
        if kwargs["method"] == "GET" and kwargs["url"].endswith("/api/webhook-events/sample-payload"):
            return _FakeResponse(200, {"data": {"event": {"type": "EMAIL_SENT"}}})
        return _FakeResponse(200, {"data": {"id": 1, "success": True}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    emailbison_client.list_webhooks(api_key="k", instance_url="https://x.example")
    emailbison_client.create_webhook(
        api_key="k",
        name="Hook",
        url="https://example.com/hook",
        events=["email_sent"],
        instance_url="https://x.example",
    )
    emailbison_client.get_webhook(api_key="k", webhook_id=1, instance_url="https://x.example")
    emailbison_client.update_webhook(
        api_key="k",
        webhook_id=1,
        name="Hook2",
        url="https://example.com/hook2",
        events=["lead_replied"],
        instance_url="https://x.example",
    )
    emailbison_client.delete_webhook(api_key="k", webhook_id=1, instance_url="https://x.example")
    emailbison_client.get_webhook_event_types(api_key="k", instance_url="https://x.example")
    emailbison_client.get_sample_webhook_payload(
        api_key="k",
        event_type="email_sent",
        instance_url="https://x.example",
    )
    emailbison_client.send_test_webhook_event(
        api_key="k",
        event_type="email_sent",
        url="https://example.com/hook",
        instance_url="https://x.example",
    )

    assert calls[0] == ("GET", "https://x.example/api/webhook-url", None)
    assert calls[1] == (
        "POST",
        "https://x.example/api/webhook-url",
        {"name": "Hook", "url": "https://example.com/hook", "events": ["email_sent"]},
    )
    assert calls[2] == ("GET", "https://x.example/api/webhook-url/1", None)
    assert calls[3] == (
        "PUT",
        "https://x.example/api/webhook-url/1",
        {"name": "Hook2", "url": "https://example.com/hook2", "events": ["lead_replied"]},
    )
    assert calls[4] == ("DELETE", "https://x.example/api/webhook-url/1", None)
    assert calls[5] == ("GET", "https://x.example/api/webhook-events/event-types", None)
    assert calls[6] == ("GET", "https://x.example/api/webhook-events/sample-payload", None)
    assert calls[7] == (
        "POST",
        "https://x.example/api/webhook-events/test-event",
        {"event_type": "email_sent", "url": "https://example.com/hook"},
    )


def test_bulk_parity_endpoints(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("json_payload")))
        if kwargs["url"].endswith("/api/sender-emails/bulk"):
            return _FakeResponse(201, {"data": [{"id": 1}]})
        if kwargs["url"].endswith("/api/leads/bulk/csv"):
            return _FakeResponse(201, {"data": [{"id": 10}]})
        return _FakeResponse(200, {"data": {"success": True}})

    monkeypatch.setattr(emailbison_client, "_request_with_retry", _fake_request_with_retry)
    emailbison_client.bulk_delete_campaigns(api_key="k", campaign_ids=[1, 2], instance_url="https://x.example")
    emailbison_client.bulk_update_sender_email_signatures(
        api_key="k",
        sender_email_ids=[11, 12],
        email_signature="<p>Sig</p>",
        instance_url="https://x.example",
    )
    emailbison_client.bulk_update_sender_email_daily_limits(
        api_key="k",
        sender_email_ids=[11, 12],
        daily_limit=25,
        instance_url="https://x.example",
    )
    emailbison_client.bulk_create_sender_emails(
        api_key="k",
        payload={"rows": []},
        instance_url="https://x.example",
    )
    emailbison_client.bulk_create_leads_csv(
        api_key="k",
        payload={"csv": "email\nx@example.com"},
        instance_url="https://x.example",
    )
    emailbison_client.bulk_update_lead_status(
        api_key="k",
        lead_ids=[31, 32],
        status="verified",
        instance_url="https://x.example",
    )
    emailbison_client.bulk_delete_leads(
        api_key="k",
        lead_ids=[31, 32],
        instance_url="https://x.example",
    )

    assert calls[0] == ("DELETE", "https://x.example/api/campaigns/bulk", {"campaign_ids": [1, 2]})
    assert calls[1] == (
        "PATCH",
        "https://x.example/api/sender-emails/signatures/bulk",
        {"sender_email_ids": [11, 12], "email_signature": "<p>Sig</p>"},
    )
    assert calls[2] == (
        "PATCH",
        "https://x.example/api/sender-emails/daily-limits/bulk",
        {"sender_email_ids": [11, 12], "daily_limit": 25},
    )
    assert calls[3] == ("POST", "https://x.example/api/sender-emails/bulk", {"rows": []})
    assert calls[4] == ("POST", "https://x.example/api/leads/bulk/csv", {"csv": "email\nx@example.com"})
    assert calls[5] == ("PATCH", "https://x.example/api/leads/bulk-update-status", {"lead_ids": [31, 32], "status": "verified"})
    assert calls[6] == ("DELETE", "https://x.example/api/leads/bulk", {"lead_ids": [31, 32]})


def test_registry_covers_all_public_client_methods():
    excluded = {"webhook_resource_paths"}
    public_callables = {
        name
        for name, value in vars(emailbison_client).items()
        if isinstance(value, types.FunctionType) and not name.startswith("_") and name not in excluded
    }
    registered = set(emailbison_client.EMAILBISON_IMPLEMENTED_ENDPOINT_REGISTRY.keys())
    assert public_callables == registered
