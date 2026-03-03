from __future__ import annotations

from src.orchestrator import step_executor
from src.providers.emailbison.client import EmailBisonProviderError


def test_execute_step_email_happy_path(monkeypatch):
    captured: dict = {}

    def _fake_compose_new_email(**kwargs):
        captured.update(kwargs)
        return {"id": "em_123", "status": "queued"}

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "emailbison")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "eb_key", "instance_url": "https://app.emailbison.com"},
    )
    monkeypatch.setattr(step_executor, "compose_new_email", _fake_compose_new_email)

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_1",
            "channel": "email",
            "execution_mode": "direct_single_touch",
            "action_type": "send_email",
            "action_config": {
                "subject": "Hello",
                "message": "<p>Hi there</p>",
                "sender_email_id": 7,
            },
        },
        lead={"email": "lead@example.com", "first_name": "Ada", "last_name": "Lovelace"},
        lead_provider_ids={},
    )

    assert result.success is True
    assert result.provider_slug == "emailbison"
    assert result.external_id == "em_123"
    assert captured["api_key"] == "eb_key"
    assert captured["to_emails"] == [{"email_address": "lead@example.com", "name": "Ada Lovelace"}]
    assert captured["subject"] == "Hello"
    assert captured["message"] == "<p>Hi there</p>"
    assert captured["sender_email_id"] == 7


def test_execute_step_linkedin_campaign_mediated_happy_path(monkeypatch):
    captured: dict = {}

    def _fake_add_campaign_leads(**kwargs):
        captured.update(kwargs)
        return {"id": "enqueue_1", "status": "ok"}

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "heyreach")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "hr_key", "instance_url": None},
    )
    monkeypatch.setattr(step_executor, "add_campaign_leads", _fake_add_campaign_leads)

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_2",
            "channel": "linkedin",
            "execution_mode": "campaign_mediated",
            "action_type": "send_connection_request",
            "provider_campaign_id": "camp_900",
            "action_config": {},
        },
        lead={
            "email": "lead@example.com",
            "first_name": "Grace",
            "last_name": "Hopper",
            "linkedin_url": "https://linkedin.com/in/grace-hopper",
            "company_name": "Navy",
        },
        lead_provider_ids={"heyreach": "lead_ext_44"},
    )

    assert result.success is True
    assert result.provider_slug == "heyreach"
    assert captured["api_key"] == "hr_key"
    assert captured["campaign_id"] == "camp_900"
    assert len(captured["leads"]) == 1
    assert captured["leads"][0] == {
        "firstName": "Grace",
        "lastName": "Hopper",
        "linkedinUrl": "https://linkedin.com/in/grace-hopper",
        "emailAddress": "lead@example.com",
        "companyName": "Navy",
        "id": "lead_ext_44",
    }


def test_execute_step_direct_mail_postcard_happy_path(monkeypatch):
    captured: dict = {}

    def _fake_create_postcard(**kwargs):
        captured.update(kwargs)
        return {"id": "psc_001", "status": "queued"}

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "lob")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "lob_key", "instance_url": None},
    )
    monkeypatch.setattr(step_executor, "create_postcard", _fake_create_postcard)

    payload = {
        "description": "Postcard touch",
        "to": {"name": "Ada Lovelace", "address_line1": "1 Main", "address_city": "SF", "address_state": "CA"},
        "from": "adr_123",
        "front": "<html>front</html>",
        "back": "<html>back</html>",
    }
    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_3",
            "channel": "direct_mail",
            "execution_mode": "direct_single_touch",
            "action_type": "send_postcard",
            "action_config": payload,
        },
        lead={},
        lead_provider_ids={},
    )

    assert result.success is True
    assert result.external_id == "psc_001"
    assert captured["api_key"] == "lob_key"
    assert captured["payload"] == payload


def test_execute_step_direct_mail_letter_happy_path(monkeypatch):
    captured: dict = {}

    def _fake_create_letter(**kwargs):
        captured.update(kwargs)
        return {"id": "ltr_001", "status": "queued"}

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "lob")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "lob_key", "instance_url": None},
    )
    monkeypatch.setattr(step_executor, "create_letter", _fake_create_letter)

    payload = {
        "description": "Letter touch",
        "to": {"name": "Ada Lovelace", "address_line1": "1 Main", "address_city": "SF", "address_state": "CA"},
        "from": "adr_123",
        "file": "https://example.com/letter.pdf",
    }
    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_4",
            "channel": "direct_mail",
            "execution_mode": "direct_single_touch",
            "action_type": "send_letter",
            "action_config": payload,
        },
        lead={},
        lead_provider_ids={},
    )

    assert result.success is True
    assert result.external_id == "ltr_001"
    assert captured["payload"] == payload


def test_execute_step_provider_error_maps_retryable(monkeypatch):
    def _fake_compose_new_email(**_kwargs):
        raise EmailBisonProviderError("EmailBison API returned HTTP 503: upstream unavailable")

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "emailbison")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "eb_key", "instance_url": None},
    )
    monkeypatch.setattr(step_executor, "compose_new_email", _fake_compose_new_email)

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_1",
            "channel": "email",
            "execution_mode": "direct_single_touch",
            "action_type": "send_email",
            "action_config": {"subject": "Hi", "message": "Body", "sender_email_id": 7},
        },
        lead={"email": "lead@example.com"},
        lead_provider_ids={},
    )

    assert result.success is False
    assert result.retryable is True
    assert "HTTP 503" in (result.error_message or "")


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTableQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def is_(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _FakeResult(self._data)


class _FakeSupabase:
    def __init__(self, organizations_data):
        self._organizations_data = organizations_data

    def table(self, table_name: str):
        if table_name != "organizations":
            raise AssertionError(f"Unexpected table requested: {table_name}")
        return _FakeTableQuery(self._organizations_data)


def test_get_org_provider_credentials_missing_credentials_raises(monkeypatch):
    monkeypatch.setattr(step_executor, "supabase", _FakeSupabase([{"provider_configs": {}}]))
    try:
        step_executor.get_org_provider_credentials("org_1", "emailbison")
    except step_executor.StepExecutionError as exc:
        assert "Missing org-level emailbison API key" in str(exc)
        assert exc.retryable is False
    else:
        raise AssertionError("Expected StepExecutionError when provider credentials are missing")


def test_execute_step_linkedin_missing_provider_campaign_id(monkeypatch):
    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "heyreach")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "hr_key", "instance_url": None},
    )

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_2",
            "channel": "linkedin",
            "execution_mode": "campaign_mediated",
            "action_type": "send_linkedin_message",
            "action_config": {},
            "provider_campaign_id": None,
        },
        lead={"first_name": "Grace"},
        lead_provider_ids={},
    )

    assert result.success is False
    assert result.retryable is False
    assert "provider_campaign_id" in (result.error_message or "")


def test_execute_step_unknown_channel_returns_failure(monkeypatch):
    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "emailbison")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "k", "instance_url": None},
    )

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_x",
            "channel": "sms",
            "execution_mode": "direct_single_touch",
            "action_type": "send_sms",
            "action_config": {},
        },
        lead={},
        lead_provider_ids={},
    )

    assert result.success is False
    assert result.retryable is False
    assert "Unsupported channel/execution_mode" in (result.error_message or "")
