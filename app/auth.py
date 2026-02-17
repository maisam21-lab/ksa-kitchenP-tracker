"""
RBAC for KSA Kitchens Tracker.
Roles: associate_viewer (Master Kitchens only), manager_viewer (+ Live Dashboard), super_user (all + tools).
"""
from __future__ import annotations

import os
from pathlib import Path

# Avoid circular import: we need get_conn and list_allowed_users from tracker_app.
# Caller (tracker_app) will pass get_user_role the resolved allowlist or we read from DB via passed helpers.
# We use a minimal interface: get_conn and list_allowed_users_with_roles.

ROLE_ASSOCIATE = "associate_viewer"
ROLE_MANAGER = "manager_viewer"
ROLE_SUPER = "super_user"

ROLE_ORDER = [ROLE_ASSOCIATE, ROLE_MANAGER, ROLE_SUPER]


def role_level(role: str | None) -> int:
    """Higher = more access. associate=0, manager=1, super=2."""
    if not role:
        return -1
    try:
        return ROLE_ORDER.index(role)
    except ValueError:
        return -1


def has_min_role(user_role: str | None, min_role: str) -> bool:
    """True if user_role has at least the access of min_role."""
    return role_level(user_role) >= role_level(min_role)


def get_user_role(
    identifier: str,
    *,
    is_developer: bool = False,
    list_allowed_with_roles=None,
    allowlist_ids_from_secrets=None,
    secrets_roles: dict | None = None,
) -> str | None:
    """
    Resolve role for the given email/name.
    - If is_developer: return super_user.
    - Else if identifier not in allowlist: return None.
    - Else return role from DB or from secrets_roles (email -> role), default associate_viewer.
    list_allowed_with_roles: callable () -> list[dict] with keys identifier, role (optional).
    allowlist_ids_from_secrets: callable () -> set[str] of allowed ids.
    secrets_roles: optional dict mapping identifier (lower) -> role from secrets.
    """
    if is_developer:
        return ROLE_SUPER
    id_ = (identifier or "").strip().lower()
    if not id_:
        return None

    # Allowed list check: from secrets IDs or from DB
    allowed_ids = set()
    if allowlist_ids_from_secrets:
        allowed_ids = allowlist_ids_from_secrets()
    if list_allowed_with_roles:
        for row in list_allowed_with_roles():
            s = (row.get("identifier") or "").strip().lower()
            if s:
                allowed_ids.add(s)
    if id_ not in allowed_ids:
        return None

    # Resolve role: secrets_roles (e.g. from [allowed_user_roles] in TOML) override; then DB; then default
    role = ROLE_ASSOCIATE
    if secrets_roles and id_ in secrets_roles:
        role = secrets_roles[id_] or ROLE_ASSOCIATE
    if list_allowed_with_roles:
        for row in list_allowed_with_roles():
            if (row.get("identifier") or "").strip().lower() == id_:
                r = (row.get("role") or "").strip()
                if r in ROLE_ORDER:
                    role = r
                break
    return role if role in ROLE_ORDER else ROLE_ASSOCIATE
