from __future__ import annotations

import types

from src.providers.lob import client as lob_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_verify_us_paths_and_basic_auth(monkeypatch):
    calls: list[tuple[str, str, tuple[str, str] | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs.get("auth")))
        return _FakeResponse(200, {"id": "us_ver_1"})

    monkeypatch.setattr(lob_client, "_request_with_retry", _fake_request_with_retry)
    lob_client.verify_address_us_single(
        api_key="lob-test-key",
        payload={"primary_line": "1 Main", "city": "San Francisco", "state": "CA", "zip_code": "94107"},
        base_url="https://lob.example",
    )
    lob_client.verify_address_us_bulk(
        api_key="lob-test-key",
        payload={"addresses": []},
        base_url="https://lob.example",
    )

    assert calls[0] == ("POST", "https://lob.example/v1/us_verifications", ("lob-test-key", ""))
    assert calls[1] == ("POST", "https://lob.example/v1/bulk/us_verifications", ("lob-test-key", ""))


def test_idempotency_material_header_vs_query_and_mutual_exclusion():
    header_only, query_only = lob_client.build_idempotency_material(header_key="k1")
    assert header_only == {"Idempotency-Key": "k1"}
    assert query_only == {}

    header_only, query_only = lob_client.build_idempotency_material(query_key="k2")
    assert header_only == {}
    assert query_only == {"idempotency_key": "k2"}

    try:
        lob_client.build_idempotency_material(header_key="k1", query_key="k2")
    except lob_client.LobProviderError as exc:
        assert "cannot send both header and query idempotency keys" in str(exc).lower()
    else:
        raise AssertionError("Expected LobProviderError for mutually exclusive idempotency inputs")


def test_create_postcard_and_letter_idempotency_dispatch(monkeypatch):
    calls: list[tuple[str, str, dict[str, str], dict | None]] = []

    def _fake_request_with_retry(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], kwargs["headers"], kwargs.get("params")))
        return _FakeResponse(200, {"id": "ok"})

    monkeypatch.setattr(lob_client, "_request_with_retry", _fake_request_with_retry)
    lob_client.create_postcard(
        api_key="lob-test-key",
        payload={"description": "a"},
        idempotency_key="idem-1",
        idempotency_in_query=False,
        base_url="https://lob.example",
    )
    lob_client.create_letter(
        api_key="lob-test-key",
        payload={"description": "b"},
        idempotency_key="idem-2",
        idempotency_in_query=True,
        base_url="https://lob.example",
    )

    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://lob.example/v1/postcards"
    assert calls[0][2]["Idempotency-Key"] == "idem-1"
    assert calls[0][3] is None

    assert calls[1][0] == "POST"
    assert calls[1][1] == "https://lob.example/v1/letters"
    assert "Idempotency-Key" not in calls[1][2]
    assert calls[1][3] == {"idempotency_key": "idem-2"}


def test_error_category_and_retryable_contract():
    transient = lob_client.LobProviderError("Lob API returned HTTP 503: upstream unavailable")
    terminal = lob_client.LobProviderError("Invalid Lob API key")

    assert transient.category == "transient"
    assert transient.retryable is True
    assert terminal.category == "terminal"
    assert terminal.retryable is False


def test_registry_covers_all_public_client_methods():
    excluded = {"build_idempotency_material"}
    public_callables = {
        name
        for name, value in vars(lob_client).items()
        if isinstance(value, types.FunctionType) and not name.startswith("_") and name not in excluded
    }
    registered = set(lob_client.LOB_IMPLEMENTED_ENDPOINT_REGISTRY.keys())
    assert public_callables == registered
