from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app
from src.routers import direct_mail as direct_mail_router


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name: str, db: "FakeSupabase"):
        self.table_name = table_name
        self.db = db
        self.operation = "select"
        self.filters = []
        self.insert_payload = None
        self.update_payload = None

    def select(self, _fields: str):
        self.operation = "select"
        return self

    def insert(self, payload: dict):
        self.operation = "insert"
        self.insert_payload = payload
        return self

    def update(self, payload: dict):
        self.operation = "update"
        self.update_payload = payload
        return self

    def eq(self, key: str, value):
        self.filters.append(("eq", key, value))
        return self

    def is_(self, key: str, value):
        self.filters.append(("is", key, value))
        return self

    def _matches(self, row: dict) -> bool:
        for kind, key, value in self.filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "is" and value == "null" and row.get(key) is not None:
                return False
        return True

    def execute(self):
        table = self.db.tables.setdefault(self.table_name, [])
        if self.operation == "insert":
            payload = dict(self.insert_payload or {})
            payload.setdefault("id", f"{self.table_name}-{len(table)+1}")
            payload.setdefault("created_at", _ts())
            payload.setdefault("updated_at", _ts())
            table.append(payload)
            return FakeResponse([payload])

        if self.operation == "update":
            updated = []
            for row in table:
                if self._matches(row):
                    row.update(self.update_payload or {})
                    updated.append(dict(row))
            return FakeResponse(updated)

        rows = [dict(row) for row in table if self._matches(row)]
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
        "companies": [{"id": "c-1", "org_id": "org-1", "deleted_at": None}],
        "capabilities": [{"id": "cap-direct-mail", "slug": "direct_mail"}],
        "providers": [{"id": "prov-lob", "slug": "lob", "capability_id": "cap-direct-mail"}],
        "company_entitlements": [
            {
                "id": "ent-1",
                "org_id": "org-1",
                "company_id": "c-1",
                "capability_id": "cap-direct-mail",
                "provider_id": "prov-lob",
                "status": "connected",
                "provider_config": {},
                "deleted_at": None,
                "updated_at": _ts(),
            }
        ],
        "organizations": [{"id": "org-1", "deleted_at": None, "provider_configs": {"lob": {"api_key": "lob-key"}}}],
        "company_direct_mail_pieces": [],
    }


def test_direct_mail_happy_path_verify_postcards_letters(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(direct_mail_router, "supabase", fake_db)
    monkeypatch.setattr(
        direct_mail_router,
        "lob_verify_address_us_single",
        lambda **kwargs: {
            "deliverability": "deliverable",
            "primary_line": "1 Main St",
            "city": "San Francisco",
            "state": "CA",
            "zip_code": "94107",
        },
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_verify_address_us_bulk",
        lambda **kwargs: {
            "addresses": [
                {"deliverability": "deliverable", "primary_line": "1 Main St", "city": "San Francisco", "state": "CA"},
                {"deliverability": "undeliverable", "primary_line": "404 Nowhere", "city": "NA", "state": "CA"},
            ]
        },
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_create_postcard",
        lambda **kwargs: {"id": "psc_1", "status": "queued", "metadata": {"job": "a"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_list_postcards",
        lambda **kwargs: {"data": [{"id": "psc_1", "status": "processed", "metadata": {"job": "a"}, "send_date": _ts()}]},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_get_postcard",
        lambda **kwargs: {"id": "psc_1", "status": "in_transit", "metadata": {"job": "a"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_cancel_postcard",
        lambda **kwargs: {"id": "psc_1", "status": "cancelled", "metadata": {"job": "a"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_create_letter",
        lambda **kwargs: {"id": "ltr_1", "status": "queued", "metadata": {"job": "b"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_list_letters",
        lambda **kwargs: {"data": [{"id": "ltr_1", "status": "processed", "metadata": {"job": "b"}, "send_date": _ts()}]},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_get_letter",
        lambda **kwargs: {"id": "ltr_1", "status": "delivered", "metadata": {"job": "b"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_cancel_letter",
        lambda **kwargs: {"id": "ltr_1", "status": "cancelled", "metadata": {"job": "b"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_create_self_mailer",
        lambda **kwargs: {"id": "sfm_1", "status": "queued", "metadata": {"job": "c"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_list_self_mailers",
        lambda **kwargs: {"data": [{"id": "sfm_1", "status": "processed", "metadata": {"job": "c"}, "send_date": _ts()}]},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_get_self_mailer",
        lambda **kwargs: {"id": "sfm_1", "status": "in_transit", "metadata": {"job": "c"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_cancel_self_mailer",
        lambda **kwargs: {"id": "sfm_1", "status": "cancelled", "metadata": {"job": "c"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_create_check",
        lambda **kwargs: {"id": "chk_1", "status": "queued", "metadata": {"job": "d"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_list_checks",
        lambda **kwargs: {"data": [{"id": "chk_1", "status": "processed", "metadata": {"job": "d"}, "send_date": _ts()}]},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_get_check",
        lambda **kwargs: {"id": "chk_1", "status": "delivered", "metadata": {"job": "d"}, "send_date": _ts()},
    )
    monkeypatch.setattr(
        direct_mail_router,
        "lob_cancel_check",
        lambda **kwargs: {"id": "chk_1", "status": "cancelled", "metadata": {"job": "d"}, "send_date": _ts()},
    )

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    verify = client.post("/api/direct-mail/verify-address/us", json={"payload": {"primary_line": "1 Main St"}})
    assert verify.status_code == 200
    assert verify.json()["status"] == "deliverable"
    assert verify.json()["deliverability"] == "deliverable"
    assert verify.json()["normalized_address"]["city"] == "San Francisco"

    verify_bulk = client.post("/api/direct-mail/verify-address/us/bulk", json={"payload": {"addresses": []}})
    assert verify_bulk.status_code == 200
    assert len(verify_bulk.json()) == 2
    assert verify_bulk.json()[0]["status"] == "deliverable"

    postcard_create = client.post(
        "/api/direct-mail/postcards",
        json={"payload": {"description": "Postcard"}, "idempotency_key": "idem-1", "idempotency_location": "header"},
    )
    assert postcard_create.status_code == 201
    assert postcard_create.json()["id"] == "psc_1"
    assert postcard_create.json()["type"] == "postcard"
    assert postcard_create.json()["status"] == "queued"

    postcard_list = client.get("/api/direct-mail/postcards")
    assert postcard_list.status_code == 200
    assert postcard_list.json()["pieces"][0]["status"] == "ready_for_mail"

    postcard_get = client.get("/api/direct-mail/postcards/psc_1")
    assert postcard_get.status_code == 200
    assert postcard_get.json()["status"] == "in_transit"

    postcard_cancel = client.post("/api/direct-mail/postcards/psc_1/cancel")
    assert postcard_cancel.status_code == 200
    assert postcard_cancel.json()["status"] == "canceled"

    letter_create = client.post(
        "/api/direct-mail/letters",
        json={"payload": {"description": "Letter"}, "idempotency_key": "idem-2", "idempotency_location": "query"},
    )
    assert letter_create.status_code == 201
    assert letter_create.json()["id"] == "ltr_1"
    assert letter_create.json()["type"] == "letter"

    letter_list = client.get("/api/direct-mail/letters")
    assert letter_list.status_code == 200
    assert letter_list.json()["pieces"][0]["status"] == "ready_for_mail"

    letter_get = client.get("/api/direct-mail/letters/ltr_1")
    assert letter_get.status_code == 200
    assert letter_get.json()["status"] == "delivered"

    letter_cancel = client.post("/api/direct-mail/letters/ltr_1/cancel")
    assert letter_cancel.status_code == 200
    assert letter_cancel.json()["status"] == "canceled"

    self_mailer_create = client.post(
        "/api/direct-mail/self-mailers",
        json={"payload": {"description": "Self mailer"}, "idempotency_key": "idem-3", "idempotency_location": "header"},
    )
    assert self_mailer_create.status_code == 201
    assert self_mailer_create.json()["id"] == "sfm_1"
    assert self_mailer_create.json()["type"] == "self_mailer"

    self_mailer_list = client.get("/api/direct-mail/self-mailers")
    assert self_mailer_list.status_code == 200
    assert self_mailer_list.json()["pieces"][0]["status"] == "ready_for_mail"

    self_mailer_get = client.get("/api/direct-mail/self-mailers/sfm_1")
    assert self_mailer_get.status_code == 200
    assert self_mailer_get.json()["status"] == "in_transit"

    self_mailer_cancel = client.post("/api/direct-mail/self-mailers/sfm_1/cancel")
    assert self_mailer_cancel.status_code == 200
    assert self_mailer_cancel.json()["status"] == "canceled"

    check_create = client.post(
        "/api/direct-mail/checks",
        json={"payload": {"description": "Check"}, "idempotency_key": "idem-4", "idempotency_location": "query"},
    )
    assert check_create.status_code == 201
    assert check_create.json()["id"] == "chk_1"
    assert check_create.json()["type"] == "check"

    check_list = client.get("/api/direct-mail/checks")
    assert check_list.status_code == 200
    assert check_list.json()["pieces"][0]["status"] == "ready_for_mail"

    check_get = client.get("/api/direct-mail/checks/chk_1")
    assert check_get.status_code == 200
    assert check_get.json()["status"] == "delivered"

    check_cancel = client.post("/api/direct-mail/checks/chk_1/cancel")
    assert check_cancel.status_code == 200
    assert check_cancel.json()["status"] == "canceled"

    _clear()


def test_direct_mail_cross_company_boundary_denied(monkeypatch):
    tables = _base_tables()
    tables["companies"].append({"id": "c-2", "org_id": "org-1", "deleted_at": None})
    tables["company_direct_mail_pieces"] = [
        {
            "id": "piece-1",
            "org_id": "org-1",
            "company_id": "c-2",
            "provider_id": "prov-lob",
            "external_piece_id": "psc_other",
            "piece_type": "postcard",
            "status": "queued",
            "created_at": _ts(),
            "updated_at": _ts(),
            "deleted_at": None,
        }
    ]
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(direct_mail_router, "supabase", fake_db)

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    denied = client.get("/api/direct-mail/postcards/psc_other")
    assert denied.status_code == 404
    _clear()


def test_direct_mail_provider_dispatch_not_implemented_for_non_lob(monkeypatch):
    tables = _base_tables()
    tables["providers"].append({"id": "prov-other", "slug": "other_mail", "capability_id": "cap-direct-mail"})
    tables["company_entitlements"][0]["provider_id"] = "prov-other"
    fake_db = FakeSupabase(tables)
    monkeypatch.setattr(direct_mail_router, "supabase", fake_db)

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)
    response = client.post("/api/direct-mail/self-mailers", json={"payload": {"description": "x"}})
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert detail["type"] == "provider_not_implemented"
    assert detail["capability"] == "direct_mail"
    assert detail["provider"] == "other_mail"
    _clear()


def test_direct_mail_validation_errors(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(direct_mail_router, "supabase", fake_db)
    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    missing_payload = client.post("/api/direct-mail/self-mailers", json={"idempotency_key": "x"})
    assert missing_payload.status_code == 422

    blank_idempotency = client.post(
        "/api/direct-mail/checks",
        json={"payload": {"description": "x"}, "idempotency_key": "", "idempotency_location": "header"},
    )
    assert blank_idempotency.status_code == 422
    _clear()


def test_direct_mail_provider_error_shape_contracts(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(direct_mail_router, "supabase", fake_db)

    def _raise_transient(**kwargs):
        raise direct_mail_router.LobProviderError("Lob API returned HTTP 503: upstream unavailable")

    def _raise_terminal(**kwargs):
        raise direct_mail_router.LobProviderError("Invalid Lob API key")

    monkeypatch.setattr(direct_mail_router, "lob_create_self_mailer", _raise_transient)
    monkeypatch.setattr(direct_mail_router, "lob_create_check", _raise_terminal)

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    transient = client.post("/api/direct-mail/self-mailers", json={"payload": {"description": "x"}})
    assert transient.status_code == 503
    transient_detail = transient.json()["detail"]
    assert transient_detail["type"] == "provider_error"
    assert transient_detail["provider"] == "lob"
    assert transient_detail["retryable"] is True

    terminal = client.post("/api/direct-mail/checks", json={"payload": {"description": "x"}})
    assert terminal.status_code == 502
    terminal_detail = terminal.json()["detail"]
    assert terminal_detail["type"] == "provider_error"
    assert terminal_detail["provider"] == "lob"
    assert terminal_detail["retryable"] is False
    _clear()


def test_direct_mail_create_dispatches_idempotency_to_lob(monkeypatch):
    fake_db = FakeSupabase(_base_tables())
    monkeypatch.setattr(direct_mail_router, "supabase", fake_db)

    captured: dict[str, tuple[str | None, bool]] = {}

    def _create_postcard(**kwargs):
        captured["postcard"] = (kwargs.get("idempotency_key"), kwargs.get("idempotency_in_query"))
        return {"id": "psc_1", "status": "queued"}

    def _create_letter(**kwargs):
        captured["letter"] = (kwargs.get("idempotency_key"), kwargs.get("idempotency_in_query"))
        return {"id": "ltr_1", "status": "queued"}

    def _create_self_mailer(**kwargs):
        captured["self_mailer"] = (kwargs.get("idempotency_key"), kwargs.get("idempotency_in_query"))
        return {"id": "sfm_1", "status": "queued"}

    def _create_check(**kwargs):
        captured["check"] = (kwargs.get("idempotency_key"), kwargs.get("idempotency_in_query"))
        return {"id": "chk_1", "status": "queued"}

    monkeypatch.setattr(direct_mail_router, "lob_create_postcard", _create_postcard)
    monkeypatch.setattr(direct_mail_router, "lob_create_letter", _create_letter)
    monkeypatch.setattr(direct_mail_router, "lob_create_self_mailer", _create_self_mailer)
    monkeypatch.setattr(direct_mail_router, "lob_create_check", _create_check)

    _set_auth(AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session"))
    client = TestClient(app)

    psc = client.post(
        "/api/direct-mail/postcards",
        json={"payload": {"description": "x"}, "idempotency_key": "idem-1", "idempotency_location": "header"},
    )
    ltr = client.post(
        "/api/direct-mail/letters",
        json={"payload": {"description": "y"}, "idempotency_key": "idem-2", "idempotency_location": "query"},
    )
    sfm = client.post(
        "/api/direct-mail/self-mailers",
        json={"payload": {"description": "z"}, "idempotency_key": "idem-3", "idempotency_location": "header"},
    )
    chk = client.post(
        "/api/direct-mail/checks",
        json={"payload": {"description": "w"}, "idempotency_key": "idem-4", "idempotency_location": "query"},
    )
    assert psc.status_code == 201
    assert ltr.status_code == 201
    assert sfm.status_code == 201
    assert chk.status_code == 201
    assert captured["postcard"] == ("idem-1", False)
    assert captured["letter"] == ("idem-2", True)
    assert captured["self_mailer"] == ("idem-3", False)
    assert captured["check"] == ("idem-4", True)
    _clear()
