"""Scoped capability token generator and validator."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Final, Optional

DEFAULT_TOKEN_TTL_SECONDS: Final[int] = 3600


class TokenSecurityError(Exception):
    """Raised when capability token signature or integrity verification fails."""


class TokenExpiredError(TokenSecurityError):
    """Raised when token has exceeded its valid lifetime."""


@dataclass(frozen=True)
class CapabilityToken:
    token_id: str
    tenant_id: str
    ledger_id: str
    principal_id: str
    role: str
    capabilities: tuple[str, ...]
    issued_at: int
    expires_at: int

    def to_canonical_bytes(self) -> bytes:
        payload = {
            "token_id": self.token_id,
            "tenant_id": self.tenant_id,
            "ledger_id": self.ledger_id,
            "principal_id": self.principal_id,
            "role": self.role,
            "capabilities": sorted(self.capabilities),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def mint_capability_token(
    secret_key: bytes,
    token_id: str,
    tenant_id: str,
    ledger_id: str,
    principal_id: str,
    role: str,
    capabilities: list[str] | tuple[str, ...],
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    now: Optional[int] = None,
) -> tuple[CapabilityToken, str]:
    """Mints an immutable capability token and returns (token_obj, hex_signature)."""
    current_time = int(time.time()) if now is None else now
    expires_at = current_time + ttl_seconds

    token = CapabilityToken(
        token_id=token_id,
        tenant_id=tenant_id,
        ledger_id=ledger_id,
        principal_id=principal_id,
        role=role,
        capabilities=tuple(sorted(capabilities)),
        issued_at=current_time,
        expires_at=expires_at,
    )

    signature = hmac.new(
        secret_key,
        token.to_canonical_bytes(),
        hashlib.sha256,
    ).hexdigest()

    return token, signature


def verify_capability_token(
    secret_key: bytes,
    token: CapabilityToken,
    signature: str,
    now: Optional[int] = None,
) -> bool:
    """Verifies token HMAC signature and expiration fail-closed."""
    current_time = int(time.time()) if now is None else now

    if current_time > token.expires_at:
        raise TokenExpiredError(f"Token {token.token_id} expired at {token.expires_at}")

    expected_signature = hmac.new(
        secret_key,
        token.to_canonical_bytes(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise TokenSecurityError(f"Signature mismatch for token {token.token_id}")

    return True
