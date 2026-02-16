from fastapi.testclient import TestClient

from src.auth.context import AuthContext
from src.auth.dependencies import get_current_auth
from src.main import app


def _clear() -> None:
    app.dependency_overrides.clear()


def test_auth_context_normalizes_legacy_admin_role() -> None:
    auth = AuthContext(org_id="org-1", user_id="u-1", role="admin", company_id=None, auth_method="api_token")

    assert auth.role == "org_admin"
    assert "org.manage_users" in auth.permissions
    assert "campaigns.write" in auth.permissions


def test_auth_context_normalizes_legacy_user_role() -> None:
    auth = AuthContext(org_id="org-1", user_id="u-1", role="user", company_id="c-1", auth_method="session")

    assert auth.role == "company_member"
    assert "campaigns.read" in auth.permissions
    assert "campaigns.write" not in auth.permissions


def test_auth_me_returns_permissions() -> None:
    auth = AuthContext(
        org_id="org-1",
        user_id="u-admin",
        role="org_admin",
        company_id=None,
        auth_method="session",
    )

    async def _override():
        return auth

    app.dependency_overrides[get_current_auth] = _override
    client = TestClient(app)
    response = client.get("/api/auth/me")
    _clear()

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "org_admin"
    assert "permissions" in body
    assert "org.manage_users" in body["permissions"]
