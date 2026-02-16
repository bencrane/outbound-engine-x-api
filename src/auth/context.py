from dataclasses import dataclass
from src.auth.permissions import normalize_role, permissions_for_role


@dataclass
class AuthContext:
    """Identity context for authenticated requests."""
    org_id: str
    user_id: str
    role: str
    company_id: str | None = None
    token_id: str | None = None
    auth_method: str = "api_token"  # "api_token" or "session"
    permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.role = normalize_role(self.role)
        if self.permissions:
            self.permissions = tuple(sorted(set(self.permissions)))
            return
        self.permissions = tuple(sorted(permissions_for_role(self.role)))


@dataclass
class SuperAdminContext:
    """Identity context for super-admin requests. No org_id - operates above tenant layer."""
    super_admin_id: str
    email: str
