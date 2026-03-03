from __future__ import annotations

from src.providers.voicedrop import client as voicedrop_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | list[dict]):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_send_ringless_voicemail_ai_voice(monkeypatch):
    captured: dict = {}

    def _fake_request_with_retry(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(200, {"status": "success", "message": "queued"})

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_request_with_retry)

    result = voicedrop_client.send_ringless_voicemail(
        api_key="vd_key",
        to="17865555555",
        from_number="17865550000",
        voice_clone_id="clone_1",
        script="Hello from AI voice.",
        validate_recipient_phone=True,
        send_status_to_webhook="https://example.com/webhook",
    )

    assert result["status"] == "success"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.voicedrop.ai/v1/ringless_voicemail"
    assert captured["headers"]["auth-key"] == "vd_key"
    assert captured["json_payload"] == {
        "voice_clone_id": "clone_1",
        "script": "Hello from AI voice.",
        "to": "17865555555",
        "from": "17865550000",
        "validate_recipient_phone": True,
        "send_status_to_webhook": "https://example.com/webhook",
    }


def test_send_ringless_voicemail_static_audio(monkeypatch):
    captured: dict = {}

    def _fake_request_with_retry(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(200, {"status": "success"})

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_request_with_retry)

    result = voicedrop_client.send_ringless_voicemail(
        api_key="vd_key",
        to="17865555555",
        from_number="17865550000",
        recording_url="https://cdn.example.com/rvm.mp3",
    )

    assert result["status"] == "success"
    assert captured["json_payload"] == {
        "recording_url": "https://cdn.example.com/rvm.mp3",
        "to": "17865555555",
        "from": "17865550000",
        "validate_recipient_phone": False,
    }


def test_send_ringless_voicemail_missing_generation_input_raises():
    try:
        voicedrop_client.send_ringless_voicemail(
            api_key="vd_key",
            to="17865555555",
            from_number="17865550000",
        )
    except voicedrop_client.VoiceDropProviderError as exc:
        assert "Missing voice generation parameters" in str(exc)
    else:
        raise AssertionError("Expected VoiceDropProviderError")


def test_list_voice_clones(monkeypatch):
    def _fake_request_with_retry(**_kwargs):
        return _FakeResponse(200, [{"id": "vc_1", "name": "Clone"}])

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_request_with_retry)
    result = voicedrop_client.list_voice_clones(api_key="vd_key")
    assert result == [{"id": "vc_1", "name": "Clone"}]


def test_create_voice_clone(monkeypatch):
    captured: dict = {}

    def _fake_request_with_retry(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(200, {"status": "success", "message": "vc_1"})

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_request_with_retry)
    result = voicedrop_client.create_voice_clone(
        api_key="vd_key",
        display_name="My Clone",
        recording_url="https://cdn.example.com/clone.mp3",
    )

    assert result["status"] == "success"
    assert captured["url"] == "https://api.voicedrop.ai/v1/voice-clone"
    assert captured["json_payload"] == {
        "display_name": "My Clone",
        "recording_url": "https://cdn.example.com/clone.mp3",
    }


def test_list_sender_numbers(monkeypatch):
    def _fake_request_with_retry(**_kwargs):
        return _FakeResponse(200, {"numbers": ["17865550000", "17865550001"]})

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_request_with_retry)
    result = voicedrop_client.list_sender_numbers(api_key="vd_key")
    assert result == {"numbers": ["17865550000", "17865550001"]}


def test_validate_api_key_success_and_failure(monkeypatch):
    def _fake_success(**_kwargs):
        return _FakeResponse(200, {"status": "success"})

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_success)
    voicedrop_client.validate_api_key(api_key="vd_key")

    def _fake_failure(**_kwargs):
        return _FakeResponse(401, {"status": "error"})

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_failure)
    try:
        voicedrop_client.validate_api_key(api_key="bad_key")
    except voicedrop_client.VoiceDropProviderError as exc:
        assert "Invalid VoiceDrop API key" in str(exc)
    else:
        raise AssertionError("Expected VoiceDropProviderError")


def test_add_to_dnc_list(monkeypatch):
    captured: dict = {}

    def _fake_request_with_retry(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(200, {"status": "success"})

    monkeypatch.setattr(voicedrop_client, "_request_with_retry", _fake_request_with_retry)
    result = voicedrop_client.add_to_dnc_list(api_key="vd_key", phone="17865551111")

    assert result["status"] == "success"
    assert captured["url"] == "https://api.voicedrop.ai/v1/add-to-dnc-list"
    assert captured["json_payload"] == {"phone": "17865551111"}


def test_request_retries_on_429(monkeypatch):
    calls = {"count": 0}

    def _fake_sleep(_delay):
        return None

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return _FakeResponse(429, {"status": "error"})
            return _FakeResponse(200, {"status": "success"})

    monkeypatch.setattr(voicedrop_client.httpx, "Client", _FakeClient)
    monkeypatch.setattr(voicedrop_client.time, "sleep", _fake_sleep)

    result = voicedrop_client.list_sender_numbers(api_key="vd_key")
    assert calls["count"] == 2
    assert result["status"] == "success"


def test_non_retryable_error_on_401():
    err = voicedrop_client.VoiceDropProviderError("Invalid VoiceDrop API key")
    assert err.retryable is False
