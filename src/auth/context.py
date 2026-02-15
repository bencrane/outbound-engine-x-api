from dataclasses import dataclass


@dataclass
class AuthContext:
    """Identity context for authenticated requests."""
    org_id: str
    user_id: str
    company_id: str | None = None
    token_id: str | None = None
    auth_method: str = "api_token"  # "api_token" or "session"
