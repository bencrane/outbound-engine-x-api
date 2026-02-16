from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.routers import email_outreach as email_outreach_router


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


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_auth(auth: AuthContext):
    async def _override():
        return auth

    app.dependency_overrides[get_current_auth] = _override


def _clear():
    app.dependency_overrides.clear()


def _base_tables():
    return {
        "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"emailbison": {"api_key": "eb-key", "instance_url": "https://eb.example"}}}],
        "providers": [
            {"id": "prov-emailbison", "slug": "emailbison"},
            {"id": "prov-smartlead", "slug": "smartlead"},
        ],
        "company_campaigns": [
            {
                "id": "cmp-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "provider_id": "prov-emailbison",
                "external_campaign_id": "777",
                "deleted_at": None,
                "updated_at": _ts(),
            }
        ],
        "company_campaign_leads": [
            {
                "id": "lead-1",
                "org_id": "org-1",
                "company_campaign_id": "cmp-1",
                "external_lead_id": "888",
                "deleted_at": None,
            }
        ],
        "company_inboxes": [
            {
                "id": "inbox-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "provider_id": "prov-emailbison",
                "external_account_id": "999",
                "deleted_at": None,
            }
        ],
    }


def test_tags_custom_variables_and_blocklist_happy_paths(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    monkeypatch.setattr(email_outreach_router, "emailbison_list_tags", lambda **kwargs: [{"id": 1, "name": "Important"}])
    monkeypatch.setattr(email_outreach_router, "emailbison_create_tag", lambda **kwargs: {"id": 2, "name": "Urgent"})
    monkeypatch.setattr(email_outreach_router, "emailbison_list_custom_variables", lambda **kwargs: [{"id": 1, "name": "linkedin"}])
    monkeypatch.setattr(email_outreach_router, "emailbison_create_custom_variable", lambda **kwargs: {"id": 2, "name": "timezone"})
    monkeypatch.setattr(email_outreach_router, "emailbison_list_blacklisted_emails", lambda **kwargs: [{"id": 1, "email": "a@example.com"}])
    monkeypatch.setattr(email_outreach_router, "emailbison_create_blacklisted_email", lambda **kwargs: {"id": 2, "email": "b@example.com"})
    monkeypatch.setattr(email_outreach_router, "emailbison_list_blacklisted_domains", lambda **kwargs: [{"id": 1, "domain": "example.com"}])
    monkeypatch.setattr(email_outreach_router, "emailbison_create_blacklisted_domain", lambda **kwargs: {"id": 2, "domain": "b.com"})

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    assert client.get("/api/email-outreach/tags").status_code == 200
    assert client.post("/api/email-outreach/tags", json={"name": "Urgent"}).status_code == 200
    assert client.get("/api/email-outreach/custom-variables").status_code == 200
    assert client.post("/api/email-outreach/custom-variables", json={"name": "timezone"}).status_code == 200
    assert client.get("/api/email-outreach/blocklist/emails").status_code == 200
    assert client.post("/api/email-outreach/blocklist/emails", json={"email": "b@example.com"}).status_code == 200
    assert client.get("/api/email-outreach/blocklist/domains").status_code == 200
    assert client.post("/api/email-outreach/blocklist/domains", json={"domain": "b.com"}).status_code == 200

    _clear()


def test_attach_tags_auth_tenant_boundary(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"][0]["company_id"] = "c-2"
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post(
        "/api/email-outreach/tags/attach/campaigns",
        json={"tag_ids": [1], "campaign_ids": ["cmp-1"]},
    )
    assert response.status_code == 404

    _clear()


def test_attach_tags_malformed_external_identifier_tolerance(monkeypatch):
    tables = _base_tables()
    tables["company_campaign_leads"][0]["external_lead_id"] = "not-a-number"
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post(
        "/api/email-outreach/tags/attach/leads",
        json={"tag_ids": [1], "campaign_id": "cmp-1", "lead_ids": ["lead-1"]},
    )
    assert response.status_code == 400
    assert "non-numeric external identifier" in response.json()["detail"].lower()

    _clear()


def test_provider_error_shape_contracts(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)

    def _raise_transient(**kwargs):
        raise email_outreach_router.EmailBisonProviderError("EmailBison API returned HTTP 503: upstream unavailable")

    def _raise_terminal(**kwargs):
        raise email_outreach_router.EmailBisonProviderError("Invalid EmailBison API key")

    monkeypatch.setattr(email_outreach_router, "emailbison_list_tags", _raise_transient)
    monkeypatch.setattr(email_outreach_router, "emailbison_create_blacklisted_domain", _raise_terminal)

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    transient = client.get("/api/email-outreach/tags")
    assert transient.status_code == 503
    transient_detail = transient.json()["detail"]
    assert transient_detail["type"] == "provider_error"
    assert transient_detail["provider"] == "emailbison"
    assert transient_detail["retryable"] is True

    terminal = client.post("/api/email-outreach/blocklist/domains", json={"domain": "a.com"})
    assert terminal.status_code == 502
    terminal_detail = terminal.json()["detail"]
    assert terminal_detail["type"] == "provider_error"
    assert terminal_detail["provider"] == "emailbison"
    assert terminal_detail["retryable"] is False

    _clear()


def test_attach_and_remove_tags_for_inboxes_happy_path(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    monkeypatch.setattr(email_outreach_router, "emailbison_attach_tags_to_sender_emails", lambda **kwargs: {"success": True})
    monkeypatch.setattr(email_outreach_router, "emailbison_remove_tags_from_sender_emails", lambda **kwargs: {"success": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    attach = client.post("/api/email-outreach/tags/attach/inboxes", json={"tag_ids": [1], "inbox_ids": ["inbox-1"]})
    remove = client.post("/api/email-outreach/tags/remove/inboxes", json={"tag_ids": [1], "inbox_ids": ["inbox-1"]})
    assert attach.status_code == 200
    assert remove.status_code == 200

    _clear()


def test_workspace_account_settings_and_stats_happy_paths(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    monkeypatch.setattr(email_outreach_router, "emailbison_get_workspace_account_details", lambda **kwargs: {"id": 1})
    monkeypatch.setattr(email_outreach_router, "emailbison_get_workspace_stats", lambda **kwargs: {"emails_sent": "10"})
    monkeypatch.setattr(
        email_outreach_router,
        "emailbison_get_workspace_master_inbox_settings",
        lambda **kwargs: {"sync_all_emails": True},
    )
    monkeypatch.setattr(
        email_outreach_router,
        "emailbison_update_workspace_master_inbox_settings",
        lambda **kwargs: {"sync_all_emails": False},
    )
    monkeypatch.setattr(
        email_outreach_router,
        "emailbison_get_campaign_events_stats",
        lambda **kwargs: [{"label": "Sent", "dates": [["2026-02-16", 2]]}],
    )
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    assert client.get("/api/email-outreach/workspace/account").status_code == 200
    assert client.post("/api/email-outreach/workspace/stats", json={"start_date": "2026-02-01", "end_date": "2026-02-16"}).status_code == 200
    assert client.get("/api/email-outreach/workspace/master-inbox-settings").status_code == 200
    assert client.patch("/api/email-outreach/workspace/master-inbox-settings", json={"sync_all_emails": False}).status_code == 200
    events = client.post(
        "/api/email-outreach/workspace/campaign-events/stats",
        json={"start_date": "2026-02-01", "end_date": "2026-02-16", "campaign_ids": ["cmp-1"], "inbox_ids": ["inbox-1"]},
    )
    assert events.status_code == 200

    _clear()


def test_workspace_campaign_events_auth_boundary(monkeypatch):
    tables = _base_tables()
    tables["company_campaigns"][0]["company_id"] = "c-2"
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post(
        "/api/email-outreach/workspace/campaign-events/stats",
        json={"start_date": "2026-02-01", "end_date": "2026-02-16", "campaign_ids": ["cmp-1"]},
    )
    assert response.status_code == 404

    _clear()


def test_workspace_campaign_events_malformed_identifier_tolerance(monkeypatch):
    tables = _base_tables()
    tables["company_inboxes"][0]["external_account_id"] = "bad-id"
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))

    client = TestClient(app)
    response = client.post(
        "/api/email-outreach/workspace/campaign-events/stats",
        json={"start_date": "2026-02-01", "end_date": "2026-02-16", "inbox_ids": ["inbox-1"]},
    )
    assert response.status_code == 400
    assert "non-numeric external identifier" in response.json()["detail"].lower()

    _clear()


def test_workspace_provider_error_shape_contracts(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)

    def _raise_transient(**kwargs):
        raise email_outreach_router.EmailBisonProviderError("EmailBison API returned HTTP 503: upstream unavailable")

    def _raise_terminal(**kwargs):
        raise email_outreach_router.EmailBisonProviderError("Invalid EmailBison API key")

    monkeypatch.setattr(email_outreach_router, "emailbison_get_workspace_stats", _raise_transient)
    monkeypatch.setattr(email_outreach_router, "emailbison_update_workspace_master_inbox_settings", _raise_terminal)

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    transient = client.post("/api/email-outreach/workspace/stats", json={"start_date": "2026-02-01", "end_date": "2026-02-16"})
    assert transient.status_code == 503
    transient_detail = transient.json()["detail"]
    assert transient_detail["type"] == "provider_error"
    assert transient_detail["provider"] == "emailbison"
    assert transient_detail["retryable"] is True

    terminal = client.patch("/api/email-outreach/workspace/master-inbox-settings", json={"sync_all_emails": True})
    assert terminal.status_code == 502
    terminal_detail = terminal.json()["detail"]
    assert terminal_detail["type"] == "provider_error"
    assert terminal_detail["provider"] == "emailbison"
    assert terminal_detail["retryable"] is False

    _clear()


def test_webhook_management_happy_paths(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    monkeypatch.setattr(email_outreach_router, "emailbison_list_webhooks", lambda **kwargs: [{"id": 1}])
    monkeypatch.setattr(email_outreach_router, "emailbison_create_webhook", lambda **kwargs: {"id": 2})
    monkeypatch.setattr(email_outreach_router, "emailbison_get_webhook", lambda **kwargs: {"id": 1})
    monkeypatch.setattr(email_outreach_router, "emailbison_update_webhook", lambda **kwargs: {"id": 1, "name": "Updated"})
    monkeypatch.setattr(email_outreach_router, "emailbison_delete_webhook", lambda **kwargs: {"success": True})
    monkeypatch.setattr(email_outreach_router, "emailbison_get_webhook_event_types", lambda **kwargs: [{"id": "email_sent"}])
    monkeypatch.setattr(
        email_outreach_router,
        "emailbison_get_sample_webhook_payload",
        lambda **kwargs: {"event": {"type": "EMAIL_SENT"}},
    )
    monkeypatch.setattr(email_outreach_router, "emailbison_send_test_webhook_event", lambda **kwargs: {"success": True})
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    assert client.get("/api/email-outreach/webhooks").status_code == 200
    assert client.post(
        "/api/email-outreach/webhooks",
        json={"name": "Hook", "url": "https://example.com/hook", "events": ["email_sent"]},
    ).status_code == 200
    assert client.get("/api/email-outreach/webhooks/1").status_code == 200
    assert client.put(
        "/api/email-outreach/webhooks/1",
        json={"name": "Hook2", "url": "https://example.com/hook2", "events": ["lead_replied"]},
    ).status_code == 200
    assert client.delete("/api/email-outreach/webhooks/1").status_code == 200
    assert client.get("/api/email-outreach/webhooks/event-types").status_code == 200
    assert client.post("/api/email-outreach/webhooks/sample-payload", json={"event_type": "email_sent"}).status_code == 200
    assert client.post(
        "/api/email-outreach/webhooks/test-event",
        json={"event_type": "email_sent", "url": "https://example.com/hook"},
    ).status_code == 200

    _clear()


def test_webhook_management_malformed_payload_tolerance(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    bad_create = client.post("/api/email-outreach/webhooks", json={"name": "Missing URL"})
    assert bad_create.status_code == 422

    bad_test = client.post("/api/email-outreach/webhooks/test-event", json={"event_type": "email_sent"})
    assert bad_test.status_code == 422

    _clear()


def test_webhook_management_provider_error_shape_contracts(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(email_outreach_router, "supabase", fake_db)

    def _raise_transient(**kwargs):
        raise email_outreach_router.EmailBisonProviderError("EmailBison API returned HTTP 503: upstream unavailable")

    def _raise_terminal(**kwargs):
        raise email_outreach_router.EmailBisonProviderError("Invalid EmailBison API key")

    monkeypatch.setattr(email_outreach_router, "emailbison_list_webhooks", _raise_transient)
    monkeypatch.setattr(email_outreach_router, "emailbison_create_webhook", _raise_terminal)

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    transient = client.get("/api/email-outreach/webhooks")
    assert transient.status_code == 503
    transient_detail = transient.json()["detail"]
    assert transient_detail["type"] == "provider_error"
    assert transient_detail["provider"] == "emailbison"
    assert transient_detail["retryable"] is True

    terminal = client.post(
        "/api/email-outreach/webhooks",
        json={"name": "Hook", "url": "https://example.com/hook", "events": ["email_sent"]},
    )
    assert terminal.status_code == 502
    terminal_detail = terminal.json()["detail"]
    assert terminal_detail["type"] == "provider_error"
    assert terminal_detail["provider"] == "emailbison"
    assert terminal_detail["retryable"] is False

    _clear()
