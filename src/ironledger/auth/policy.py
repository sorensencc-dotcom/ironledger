"""Centralized RBAC policy enforcer and capability verification engine."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import sqlite3
from typing import Any

from ironledger.auth.models import (
    ROLE_CEILINGS,
    CapabilityToken,
    InsufficientScopeError,
    InvalidTokenError,
    MalformedTokenError,
    Role,
    TenantAccessDeniedError,
    TokenExpiredError,
    TokenRevokedError,
    UnauthorizedError,
)


class PolicyEnforcer:
    """Enforce capability tokens and role-based access control across operations."""

    @staticmethod
    def authorize(
        conn: sqlite3.Connection,
        raw_token: str,
        required_scope: str,
        target_ledger_id: str | None = None,
        now_utc: str | None = None,
    ) -> CapabilityToken:
        """Authorize a raw capability bearer token against required scope and tenant boundary."""
        if not isinstance(raw_token, str) or not raw_token.startswith("il_cap_") or len(raw_token) != 71:
            raise MalformedTokenError("Malformed bearer token: expected 71-char token starting with 'il_cap_'")

        computed_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        cur = conn.execute(
            """
            SELECT token_id, token_hash, ledger_id, is_global, role,
                   capabilities_json, expires_at, revoked_at, created_at
            FROM capability_tokens
            WHERE token_hash = ?
            """,
            (computed_hash,),
        )
        row = cur.fetchone()
        if row is None:
            raise InvalidTokenError("Invalid capability token")

        token_id, token_hash, ledger_id, is_global_int, role, caps_json, expires_at, revoked_at, created_at = row
        is_global = bool(is_global_int)

        if not hmac.compare_digest(token_hash, computed_hash):
            raise InvalidTokenError("Invalid capability token hash mismatch")

        if revoked_at is not None:
            raise TokenRevokedError("Capability token has been revoked")

        current_utc = now_utc or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if expires_at is not None and expires_at <= current_utc:
            raise TokenExpiredError(f"Capability token has expired at {expires_at}")

        # Check tenant scope
        if is_global:
            if role != Role.ADMIN.value or ledger_id is not None:
                raise UnauthorizedError("Global token configuration mismatch")
            # Global admin has universal access across all ledgers
        else:
            if target_ledger_id is None:
                raise TenantAccessDeniedError("Global operation requires global admin token")
            if ledger_id != target_ledger_id:
                raise TenantAccessDeniedError(
                    f"Token scoped to ledger '{ledger_id}' cannot access '{target_ledger_id}'"
                )

        # Check role ceiling and granted capabilities
        granted_scopes: list[str] = json.loads(caps_json)
        if role != Role.ADMIN.value:
            allowed_ceiling = set(ROLE_CEILINGS.get(role, []))
            if not set(granted_scopes).issubset(allowed_ceiling):
                raise UnauthorizedError(
                    f"Token capability scopes exceed permitted ceiling for role '{role}'"
                )

        # Evaluate required scope
        if role == Role.ADMIN.value or "*" in granted_scopes or required_scope in granted_scopes:
            return CapabilityToken(
                token_id=token_id,
                token_hash=token_hash,
                ledger_id=ledger_id,
                is_global=is_global,
                role=role,
                capabilities=granted_scopes,
                expires_at=expires_at,
                revoked_at=revoked_at,
                created_at=created_at,
            )

        raise InsufficientScopeError(
            f"Token lacks required scope: {required_scope} (granted: {granted_scopes})"
        )
