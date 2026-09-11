"""Capability token lifecycle management, database persistence, and revocation."""

from __future__ import annotations

import datetime
import hashlib
import json
import secrets
import sqlite3
from typing import Any
from uuid import uuid4

from ironledger.auth.models import (
    ROLE_CEILINGS,
    CapabilityToken,
    InvalidRoleCeilingError,
    Role,
)
from ironledger.ledger.topology import LEDGER_ID_PATTERN


def create_capability_token(
    conn: sqlite3.Connection,
    role: str | Role,
    ledger_id: str | None = None,
    is_global: bool = False,
    custom_capabilities: list[str] | None = None,
    expires_at: str | None = None,
    now_utc: str | None = None,
) -> tuple[str, CapabilityToken]:
    """Generate a cryptographically secure capability bearer token and persist its record."""
    role_val = role.value if isinstance(role, Role) else str(role).upper()
    if role_val not in (r.value for r in Role):
        raise ValueError(f"Invalid role '{role_val}'. Expected one of {[r.value for r in Role]}")

    if is_global:
        if role_val != Role.ADMIN.value:
            raise ValueError("Global capability tokens must have role 'ADMIN'")
        if ledger_id is not None:
            raise ValueError("Global capability tokens must have ledger_id = None")
    else:
        if not ledger_id or not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Tenant-scoped tokens require a valid ledger_id: {ledger_id!r}")

    if custom_capabilities is not None:
        if role_val != Role.ADMIN.value:
            allowed = set(ROLE_CEILINGS[role_val])
            requested = set(custom_capabilities)
            if not requested.issubset(allowed):
                exceeded = requested - allowed
                raise InvalidRoleCeilingError(
                    f"Requested capabilities {sorted(exceeded)} exceed ceiling for role '{role_val}'"
                )
        capabilities = sorted(custom_capabilities)
    else:
        capabilities = list(ROLE_CEILINGS[role_val])

    raw_token = f"il_cap_{secrets.token_hex(32)}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token_id = f"tok_{uuid4().hex[:12]}"
    created_at = now_utc or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    capabilities_json = json.dumps(capabilities, separators=(",", ":"))

    conn.execute(
        """
        INSERT INTO capability_tokens (
            token_id, token_hash, ledger_id, is_global, role,
            capabilities_json, expires_at, revoked_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            token_id,
            token_hash,
            ledger_id,
            1 if is_global else 0,
            role_val,
            capabilities_json,
            expires_at,
            created_at,
        ),
    )
    conn.commit()

    token_obj = CapabilityToken(
        token_id=token_id,
        token_hash=token_hash,
        ledger_id=ledger_id,
        is_global=is_global,
        role=role_val,
        capabilities=capabilities,
        expires_at=expires_at,
        revoked_at=None,
        created_at=created_at,
    )
    return raw_token, token_obj


def revoke_capability_token(
    conn: sqlite3.Connection,
    token_id: str,
    revoked_at: str | None = None,
) -> bool:
    """Revoke an existing capability token by token_id."""
    rev_ts = revoked_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        """
        UPDATE capability_tokens
        SET revoked_at = ?
        WHERE token_id = ? AND revoked_at IS NULL
        """,
        (rev_ts, token_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_capability_token_by_id(
    conn: sqlite3.Connection,
    token_id: str,
) -> CapabilityToken | None:
    """Retrieve a capability token record by its public token_id."""
    cur = conn.execute(
        """
        SELECT token_id, token_hash, ledger_id, is_global, role,
               capabilities_json, expires_at, revoked_at, created_at
        FROM capability_tokens
        WHERE token_id = ?
        """,
        (token_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None

    return CapabilityToken(
        token_id=row[0],
        token_hash=row[1],
        ledger_id=row[2],
        is_global=bool(row[3]),
        role=row[4],
        capabilities=json.loads(row[5]),
        expires_at=row[6],
        revoked_at=row[7],
        created_at=row[8],
    )


def list_capability_tokens(
    conn: sqlite3.Connection,
    ledger_id: str | None = None,
    include_revoked: bool = True,
) -> list[CapabilityToken]:
    """List capability tokens filtered optionally by ledger_id."""
    query = """
        SELECT token_id, token_hash, ledger_id, is_global, role,
               capabilities_json, expires_at, revoked_at, created_at
        FROM capability_tokens
        WHERE 1=1
    """
    params: list[Any] = []
    if ledger_id is not None:
        query += " AND (ledger_id = ? OR is_global = 1)"
        params.append(ledger_id)

    if not include_revoked:
        query += " AND revoked_at IS NULL"

    query += " ORDER BY created_at DESC"

    cur = conn.execute(query, params)
    tokens: list[CapabilityToken] = []
    for row in cur.fetchall():
        tokens.append(
            CapabilityToken(
                token_id=row[0],
                token_hash=row[1],
                ledger_id=row[2],
                is_global=bool(row[3]),
                role=row[4],
                capabilities=json.loads(row[5]),
                expires_at=row[6],
                revoked_at=row[7],
                created_at=row[8],
            )
        )
    return tokens
