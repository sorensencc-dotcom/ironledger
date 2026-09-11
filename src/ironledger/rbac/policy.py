"""RBAC policy definitions and hierarchical capability enforcement."""

from __future__ import annotations

from typing import Final, Iterable
from ironledger.rbac.tokens import CapabilityToken

ROLE_CAPABILITY_MATRIX: Final[dict[str, tuple[str, ...]]] = {
    "ADMIN": ("*",),
    "OPERATOR": (
        "ledger:view",
        "ledger:stage",
        "ledger:review",
        "ledger:compile",
        "price:write",
    ),
    "AUDITOR": (
        "ledger:view",
        "audit:replay",
        "audit:read",
    ),
    "INGEST_DAEMON": (
        "ledger:stage",
        "price:write",
    ),
}


class AuthorizationError(Exception):
    """Raised when a principal lacks the capability required for an action."""


def matches_capability(pattern: str, requested: str) -> bool:
    """Evaluates hierarchical wildcard capability match."""
    if pattern == "*" or pattern == requested:
        return True
    if pattern.endswith(":*"):
        prefix = pattern[:-2]
        return requested == prefix or requested.startswith(prefix + ":")
    return False


def evaluate_action_permission(
    token: CapabilityToken,
    required_capability: str,
    target_tenant_id: str,
    target_ledger_id: str,
) -> None:
    """
    Validates tenant/ledger scope isolation and verifies permission.
    Fails closed by raising AuthorizationError.
    """
    # 1. Strict Tenant & Ledger Isolation
    if token.tenant_id != "*" and token.tenant_id != target_tenant_id:
        raise AuthorizationError(
            f"Tenant boundary breach: token for '{token.tenant_id}' cannot access '{target_tenant_id}'"
        )

    if token.ledger_id != "*" and token.ledger_id != target_ledger_id:
        raise AuthorizationError(
            f"Ledger boundary breach: token for '{token.ledger_id}' cannot access '{target_ledger_id}'"
        )

    # 2. Check Granted Capabilities
    for cap in token.capabilities:
        if matches_capability(cap, required_capability):
            return

    # 3. Check Base Role Matrix Fallback
    role_caps = ROLE_CAPABILITY_MATRIX.get(token.role, ())
    for cap in role_caps:
        if matches_capability(cap, required_capability):
            return

    raise AuthorizationError(
        f"Principal '{token.principal_id}' denied capability '{required_capability}' on ledger '{target_ledger_id}'"
    )
