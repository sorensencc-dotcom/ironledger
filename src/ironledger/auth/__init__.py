"""Authentication, scoped capability tokens, and RBAC policy enforcement for IronLedger."""

from __future__ import annotations

from ironledger.auth.capabilities import (
    create_capability_token,
    get_capability_token_by_id,
    list_capability_tokens,
    revoke_capability_token,
)
from ironledger.auth.models import (
    PROTECTED_OPERATIONS,
    ROLE_CEILINGS,
    CapabilityToken,
    InsufficientScopeError,
    InvalidRoleCeilingError,
    InvalidTokenError,
    MalformedTokenError,
    Role,
    TenantAccessDeniedError,
    TokenExpiredError,
    TokenRevokedError,
    UnauthorizedError,
)
from ironledger.auth.policy import PolicyEnforcer

__all__ = [
    "Role",
    "ROLE_CEILINGS",
    "PROTECTED_OPERATIONS",
    "CapabilityToken",
    "UnauthorizedError",
    "MalformedTokenError",
    "InvalidTokenError",
    "TokenRevokedError",
    "TokenExpiredError",
    "TenantAccessDeniedError",
    "InsufficientScopeError",
    "InvalidRoleCeilingError",
    "create_capability_token",
    "revoke_capability_token",
    "get_capability_token_by_id",
    "list_capability_tokens",
    "PolicyEnforcer",
]
