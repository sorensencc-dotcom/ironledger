"""Data models, role ceilings, and exception hierarchies for RBAC capability tokens."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    READER = "READER"
    OPERATOR = "OPERATOR"
    COMPILER = "COMPILER"
    ADMIN = "ADMIN"


ROLE_CEILINGS: dict[str, list[str]] = {
    Role.READER.value: ["ledger:read", "audit:replay"],
    Role.OPERATOR.value: ["ledger:read", "staging:write", "review:decide", "audit:replay"],
    Role.COMPILER.value: ["ledger:read", "compile:execute", "audit:replay"],
    Role.ADMIN.value: ["*"],
}

PROTECTED_OPERATIONS: dict[str, tuple[str, str]] = {
    "GET /api/v1/ledger/{id}/*": ("ledger:read", Role.READER.value),
    "GET /api/v1/lineage/{id}/*": ("ledger:read", Role.READER.value),
    "POST /api/v1/replay/{id}/*": ("audit:replay", Role.READER.value),
    "POST /api/v1/staging/{id}/ingest": ("staging:write", Role.OPERATOR.value),
    "POST /api/v1/staging/{id}/decision": ("review:decide", Role.OPERATOR.value),
    "POST /api/v1/rules/{id}/*": ("review:decide", Role.OPERATOR.value),
    "POST /api/v1/prices/{id}/*": ("staging:write", Role.OPERATOR.value),
    "POST /api/v1/compile/{id}/execute": ("compile:execute", Role.COMPILER.value),
    "POST /api/v1/auth/tokens": ("*", Role.ADMIN.value),
    "POST /api/v1/ledgers": ("*", Role.ADMIN.value),
}


class UnauthorizedError(Exception):
    """Base exception for authentication and authorization failures."""


class MalformedTokenError(UnauthorizedError):
    """Bearer token does not conform to the expected format/prefix."""


class InvalidTokenError(UnauthorizedError):
    """Bearer token hash was not found in the registry."""


class TokenRevokedError(UnauthorizedError):
    """Bearer token has been explicitly revoked."""


class TokenExpiredError(UnauthorizedError):
    """Bearer token has expired based on its expires_at timestamp."""


class TenantAccessDeniedError(UnauthorizedError):
    """Bearer token is not authorized for the requested tenant ledger."""


class InsufficientScopeError(UnauthorizedError):
    """Bearer token lacks the required capability scope."""


class InvalidRoleCeilingError(ValueError):
    """Requested scopes exceed the maximum permitted ceiling for the role."""


@dataclass(frozen=True)
class CapabilityToken:
    token_id: str
    token_hash: str
    ledger_id: str | None
    is_global: bool
    role: str
    capabilities: list[str] = field(default_factory=list)
    expires_at: str | None = None
    revoked_at: str | None = None
    created_at: str | None = None

    def has_capability(self, scope: str) -> bool:
        """Check whether this token permits the given scope."""
        if self.role == Role.ADMIN.value or "*" in self.capabilities:
            return True
        return scope in self.capabilities
