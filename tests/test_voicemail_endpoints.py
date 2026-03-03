from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.routers import voicemail as voicemail_router


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name: str, db: "FakeSupabase"):
        self.table_name = table_name
        self.db = db
        self.operation = "select"
        self.filters = []

    def select(self, _fields: str):
        self.operation = "select"
        return self

    def eq(self, key: str, value):
        self.filters.append(("eq", key, value))
        return self

    def is_(self, key: str, value):
        self.filters.append(("is", key, value))
        return self

    def execute(self):
        rows = list(self.db.tables.get(self.table_name, []))
        for kind, key, value in self.filters:
            if kind == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif kind == "is" and value == "null":
                rows = [row for row in rows if row.get(key) is None]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self, tables: dict):
        self.tables = tables

    def table(self, table_name: str):
        return FakeQuery(table_name, self)


def _base_tables():
    return {
        "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
        "capabilities": [{"id": "cap-voicemail", "slug": "voicemail_drop"}],
        "providers": [{"id": "prov-voicedrop", "slug": "voicedrop"}],
        "company_entitlements": [
            {
                "id": "ent-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "capability_id": "cap-voicemail",
                "provider_id": "prov-voicedrop",
                "deleted_at": None,
            }
        ],
        "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"voicedrop": {"api_key": "vd-key"}}}],
    }


def _set_auth(auth: AuthContext):
    async def _override():
        return auth

    app.dependency_overrides[get_current_auth] = _override


def _clear():
    app.dependency_overrides.clear()


def test_send_voicemail_ai_voice(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    captured = {}

    def _send(api_key: str, **kwargs):
        captured["api_key"] = api_key
        captured["kwargs"] = kwargs
        return {"job_id": "job-1"}

    monkeypatch.setattr(voicemail_router, "voicedrop_send_ringless_voicemail", _send)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    response = client.post(
        "/api/voicemail/send",
        json={
            "to": "+15555550001",
            "from_number": "+15555550002",
            "voice_clone_id": "vc-1",
            "script": "Hello there",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["job_id"] == "job-1"
    assert captured["api_key"] == "vd-key"
    assert captured["kwargs"]["voice_clone_id"] == "vc-1"
    _clear()


def test_send_voicemail_static_audio(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_send_ringless_voicemail", lambda *args, **kwargs: {"job_id": "job-2"})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    response = client.post(
        "/api/voicemail/send",
        json={
            "to": "+15555550003",
            "from_number": "+15555550004",
            "recording_url": "https://cdn.example.com/audio.mp3",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["job_id"] == "job-2"
    _clear()


def test_send_voicemail_without_entitlement(monkeypatch):
    tables = _base_tables()
    tables["company_entitlements"] = []
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    response = client.post(
        "/api/voicemail/send",
        json={
            "to": "+15555550003",
            "from_number": "+15555550004",
            "recording_url": "https://cdn.example.com/audio.mp3",
        },
    )
    assert response.status_code == 400
    _clear()


def test_list_voice_clones(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_list_voice_clones", lambda *_args, **_kwargs: [{"id": "vc-1"}])
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.get("/api/voicemail/voice-clones")
    assert response.status_code == 200
    assert response.json()["voice_clones"][0]["id"] == "vc-1"
    _clear()


def test_create_voice_clone(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_create_voice_clone", lambda *_args, **_kwargs: {"id": "vc-2"})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.post(
        "/api/voicemail/voice-clones",
        json={"display_name": "Sales Voice", "recording_url": "https://cdn.example.com/voice.mp3"},
    )
    assert response.status_code == 200
    assert response.json()["voice_clone"]["id"] == "vc-2"
    _clear()


def test_delete_voice_clone(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_delete_voice_clone", lambda *_args, **_kwargs: {"deleted": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.delete("/api/voicemail/voice-clones/vc-1")
    assert response.status_code == 200
    assert response.json()["result"]["deleted"] is True
    _clear()


def test_preview_voice_clone(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_preview_voice_clone", lambda *_args, **_kwargs: {"preview_url": "https://x"})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.post("/api/voicemail/voice-clones/vc-1/preview", json={"script": "hello test"})
    assert response.status_code == 200
    assert response.json()["result"]["preview_url"] == "https://x"
    _clear()


def test_list_sender_numbers(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_list_sender_numbers", lambda *_args, **_kwargs: {"numbers": ["+15555551234"]})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.get("/api/voicemail/sender-numbers")
    assert response.status_code == 200
    assert response.json()["sender_numbers"]["numbers"][0] == "+15555551234"
    _clear()


def test_verify_sender_number_start(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    captured = {}

    def _request_json(**kwargs):
        captured.update(kwargs)
        return {"status": "pending"}

    monkeypatch.setattr(voicemail_router, "voicedrop_request_json", _request_json)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.post("/api/voicemail/sender-numbers/verify", json={"phone_number": "+15555550005", "method": "sms"})
    assert response.status_code == 200
    assert captured["path"] == "/v1/sender-numbers/verify"
    assert captured["json_payload"]["method"] == "sms"
    _clear()


def test_verify_sender_number_complete(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    captured = {}

    def _request_json(**kwargs):
        captured.update(kwargs)
        return {"status": "verified"}

    monkeypatch.setattr(voicemail_router, "voicedrop_request_json", _request_json)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.post(
        "/api/voicemail/sender-numbers/verify-code",
        json={"phone_number": "+15555550005", "code": "123456"},
    )
    assert response.status_code == 200
    assert captured["path"] == "/v1/sender-numbers/verify"
    assert captured["json_payload"]["code"] == "123456"
    _clear()


def test_add_to_dnc(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_add_to_dnc_list", lambda *_args, **_kwargs: {"ok": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.post("/api/voicemail/dnc", json={"phone": "+15555550006"})
    assert response.status_code == 200
    assert response.json()["result"]["ok"] is True
    _clear()


def test_export_campaign_reports(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(voicemail_router, "supabase", fake_db)
    monkeypatch.setattr(voicemail_router, "voicedrop_request_json", lambda **_kwargs: {"csv_url": "https://cdn.example.com/report.csv"})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.get("/api/voicemail/campaigns/cmp-1/reports")
    assert response.status_code == 200
    assert response.json()["result"]["csv_url"] == "https://cdn.example.com/report.csv"
    _clear()
