from __future__ import annotations

from src.orchestrator import step_executor
from src.providers.voicedrop.client import VoiceDropProviderError


def test_execute_step_voicemail_ai_voice_happy_path(monkeypatch):
    captured: dict = {}

    def _fake_send_ringless_voicemail(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "message": "queued"}

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "voicedrop")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "vd_key", "instance_url": None},
    )
    monkeypatch.setattr(step_executor, "send_ringless_voicemail", _fake_send_ringless_voicemail)

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_voice",
            "channel": "voicemail",
            "execution_mode": "direct_single_touch",
            "action_type": "send_voicemail",
            "action_config": {
                "voice_clone_id": "clone_1",
                "script": "Hi from AI voice",
                "from_number": "17865550000",
                "validate_recipient_phone": True,
                "send_status_to_webhook": "https://example.com/hook",
            },
        },
        lead={"phone": "17865551111"},
        lead_provider_ids={},
    )

    assert result.success is True
    assert result.provider_slug == "voicedrop"
    assert captured["api_key"] == "vd_key"
    assert captured["to"] == "17865551111"
    assert captured["from_number"] == "17865550000"
    assert captured["voice_clone_id"] == "clone_1"
    assert captured["script"] == "Hi from AI voice"
    assert captured["recording_url"] is None
    assert captured["validate_recipient_phone"] is True
    assert captured["send_status_to_webhook"] == "https://example.com/hook"


def test_execute_step_voicemail_static_audio_happy_path(monkeypatch):
    captured: dict = {}

    def _fake_send_ringless_voicemail(**kwargs):
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "voicedrop")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "vd_key", "instance_url": None},
    )
    monkeypatch.setattr(step_executor, "send_ringless_voicemail", _fake_send_ringless_voicemail)

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_voice",
            "channel": "voicemail",
            "execution_mode": "direct_single_touch",
            "action_type": "send_voicemail",
            "action_config": {
                "recording_url": "https://cdn.example.com/rvm.mp3",
                "from_number": "17865550000",
            },
        },
        lead={"phone_number": "17865551111"},
        lead_provider_ids={},
    )

    assert result.success is True
    assert captured["recording_url"] == "https://cdn.example.com/rvm.mp3"
    assert captured["voice_clone_id"] is None
    assert captured["script"] is None
    assert captured["to"] == "17865551111"


def test_execute_step_voicemail_missing_phone_returns_non_retryable(monkeypatch):
    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "voicedrop")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "vd_key", "instance_url": None},
    )

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_voice",
            "channel": "voicemail",
            "execution_mode": "direct_single_touch",
            "action_type": "send_voicemail",
            "action_config": {
                "recording_url": "https://cdn.example.com/rvm.mp3",
                "from_number": "17865550000",
            },
        },
        lead={},
        lead_provider_ids={},
    )

    assert result.success is False
    assert result.retryable is False
    assert "missing phone" in (result.error_message or "").lower()


def test_voicedrop_provider_error_maps_retryable(monkeypatch):
    def _fake_send_ringless_voicemail(**_kwargs):
        raise VoiceDropProviderError("VoiceDrop API returned HTTP 503: upstream unavailable")

    monkeypatch.setattr(step_executor, "get_provider_slug", lambda _provider_id: "voicedrop")
    monkeypatch.setattr(
        step_executor,
        "get_org_provider_credentials",
        lambda _org_id, _provider_slug: {"api_key": "vd_key", "instance_url": None},
    )
    monkeypatch.setattr(step_executor, "send_ringless_voicemail", _fake_send_ringless_voicemail)

    result = step_executor.execute_step(
        org_id="org_1",
        step={
            "provider_id": "prov_voice",
            "channel": "voicemail",
            "execution_mode": "direct_single_touch",
            "action_type": "send_voicemail",
            "action_config": {
                "recording_url": "https://cdn.example.com/rvm.mp3",
                "from_number": "17865550000",
            },
        },
        lead={"phone": "17865551111"},
        lead_provider_ids={},
    )

    assert result.success is False
    assert result.retryable is True
    assert "HTTP 503" in (result.error_message or "")
