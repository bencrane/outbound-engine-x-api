from __future__ import annotations

from typing import Final

LEGACY_ROLE_ALIASES: Final[dict[str, str]] = {
    "admin": "org_admin",
    "user": "company_member",
}

CANONICAL_ROLES: Final[set[str]] = {"org_admin", "company_admin", "company_member"}

ORG_MANAGE_USERS: Final[str] = "org.manage_users"
ORG_MANAGE_COMPANIES: Final[str] = "org.manage_companies"
ORG_MANAGE_ENTITLEMENTS: Final[str] = "org.manage_entitlements"
CAMPAIGNS_READ: Final[str] = "campaigns.read"
CAMPAIGNS_WRITE: Final[str] = "campaigns.write"
INBOXES_READ: Final[str] = "inboxes.read"
INBOXES_WRITE: Final[str] = "inboxes.write"
ANALYTICS_READ: Final[str] = "analytics.read"

ROLE_PERMISSION_BUNDLES: Final[dict[str, set[str]]] = {
    "org_admin": {
        ORG_MANAGE_USERS,
        ORG_MANAGE_COMPANIES,
        ORG_MANAGE_ENTITLEMENTS,
        CAMPAIGNS_READ,
        CAMPAIGNS_WRITE,
        INBOXES_READ,
        INBOXES_WRITE,
        ANALYTICS_READ,
    },
    "company_admin": {
        CAMPAIGNS_READ,
        CAMPAIGNS_WRITE,
        INBOXES_READ,
        INBOXES_WRITE,
        ANALYTICS_READ,
    },
    "company_member": {
        CAMPAIGNS_READ,
        INBOXES_READ,
        ANALYTICS_READ,
    },
}


def normalize_role(role: str) -> str:
    raw = (role or "").strip()
    normalized = LEGACY_ROLE_ALIASES.get(raw, raw)
    if normalized not in CANONICAL_ROLES:
        raise ValueError(f"Unsupported role: {role}")
    return normalized


def permissions_for_role(role: str) -> set[str]:
    normalized = normalize_role(role)
    return set(ROLE_PERMISSION_BUNDLES[normalized])


def role_has_permission(role: str, permission_key: str) -> bool:
    return permission_key in permissions_for_role(role)


def is_org_admin_role(role: str) -> bool:
    return normalize_role(role) == "org_admin"
