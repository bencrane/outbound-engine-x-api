from dataclasses import dataclass


@dataclass
class AuthContext:
    """Identity context for authenticated requests."""
    org_id: str
    user_id: str
    company_id: str | None = None
    token_id: str | None = None
    auth_method: str = "api_token"  # "api_token" or "session"


@dataclass
class SuperAdminContext:
    """Identity context for super-admin requests. No org_id - operates above tenant layer."""
    super_admin_id: str
    email: str
