"""Tests for Phase 8 Task 8.5: Scoped Capability Tokens & RBAC Policy Enforcement."""

import datetime
import sqlite3
from pathlib import Path

import pytest

from ironledger.auth import (
    PROTECTED_OPERATIONS,
    ROLE_CEILINGS,
    CapabilityToken,
    InsufficientScopeError,
    InvalidRoleCeilingError,
    InvalidTokenError,
    MalformedTokenError,
    PolicyEnforcer,
    Role,
    TenantAccessDeniedError,
    TokenExpiredError,
    TokenRevokedError,
    UnauthorizedError,
    create_capability_token,
    get_capability_token_by_id,
    list_capability_tokens,
    revoke_capability_token,
)
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ledger.topology import LedgerRegistry


@pytest.fixture
def conn(tmp_path):
    db_file = tmp_path / "auth_test.db"
    c = connect(str(db_file))
    migrations.migrate(c)
    return c


@pytest.fixture
def ledgers(conn, tmp_path):
    reg = LedgerRegistry(conn=conn, base_path=tmp_path / "ledgers")
    reg.create_ledger("Alpha Ledger", "Assets", "USD", "alpha", ledger_id="alpha")
    reg.create_ledger("Beta Ledger", "Assets", "EUR", "beta", ledger_id="beta")
    return ["alpha", "beta"]


def test_token_generation_format_and_defaults(conn, ledgers):
    """Test generating tokens produces 71-char strings starting with il_cap_ and correct defaults."""
    raw_token, token_obj = create_capability_token(
        conn=conn,
        role=Role.READER,
        ledger_id="alpha",
    )
    assert isinstance(raw_token, str)
    assert raw_token.startswith("il_cap_")
    assert len(raw_token) == 71
    assert token_obj.role == "READER"
    assert token_obj.ledger_id == "alpha"
    assert token_obj.is_global is False
    assert token_obj.capabilities == ["ledger:read", "audit:replay"]
    assert token_obj.revoked_at is None
    assert token_obj.expires_at is None

    # Verify lookup by ID
    fetched = get_capability_token_by_id(conn, token_obj.token_id)
    assert fetched is not None
    assert fetched.token_id == token_obj.token_id
    assert fetched.token_hash == token_obj.token_hash
    assert fetched.capabilities == token_obj.capabilities


def test_global_admin_token(conn):
    """Test global admin token creation and policy authorization across all tenants."""
    raw_token, token_obj = create_capability_token(
        conn=conn,
        role=Role.ADMIN,
        ledger_id=None,
        is_global=True,
    )
    assert token_obj.is_global is True
    assert token_obj.ledger_id is None
    assert token_obj.role == "ADMIN"
    assert token_obj.capabilities == ["*"]

    # Authorize across any tenant
    authed_alpha = PolicyEnforcer.authorize(conn, raw_token, "ledger:read", "alpha")
    assert authed_alpha.token_id == token_obj.token_id

    authed_beta = PolicyEnforcer.authorize(conn, raw_token, "compile:execute", "beta")
    assert authed_beta.token_id == token_obj.token_id

    # Authorize global operations (target_ledger_id is None)
    authed_global = PolicyEnforcer.authorize(conn, raw_token, "*", None)
    assert authed_global.token_id == token_obj.token_id


def test_role_ceiling_enforcement(conn, ledgers):
    """Test that custom capabilities exceeding the role ceiling are rejected."""
    # Reader attempting to request compile:execute
    with pytest.raises(InvalidRoleCeilingError, match="exceed ceiling for role 'READER'"):
        create_capability_token(
            conn=conn,
            role=Role.READER,
            ledger_id="alpha",
            custom_capabilities=["ledger:read", "compile:execute"],
        )

    # Operator attempting to request compile:execute
    with pytest.raises(InvalidRoleCeilingError, match="exceed ceiling for role 'OPERATOR'"):
        create_capability_token(
            conn=conn,
            role=Role.OPERATOR,
            ledger_id="alpha",
            custom_capabilities=["staging:write", "compile:execute"],
        )

    # Valid subset of role capabilities
    raw_sub, tok_sub = create_capability_token(
        conn=conn,
        role=Role.READER,
        ledger_id="alpha",
        custom_capabilities=["ledger:read"],
    )
    assert tok_sub.capabilities == ["ledger:read"]


def test_tenant_boundary_isolation_rejection(conn, ledgers):
    """Test that a tenant-scoped token is strictly denied access to other tenants."""
    raw_alpha, tok_alpha = create_capability_token(
        conn=conn,
        role=Role.OPERATOR,
        ledger_id="alpha",
    )

    # Access alpha -> OK
    authed = PolicyEnforcer.authorize(conn, raw_alpha, "staging:write", "alpha")
    assert authed.token_id == tok_alpha.token_id

    # Access beta -> Rejected
    with pytest.raises(TenantAccessDeniedError, match="Token scoped to ledger 'alpha' cannot access 'beta'"):
        PolicyEnforcer.authorize(conn, raw_alpha, "staging:write", "beta")

    # Access global operation -> Rejected
    with pytest.raises(TenantAccessDeniedError, match="Global operation requires global admin token"):
        PolicyEnforcer.authorize(conn, raw_alpha, "*", None)


def test_insufficient_scope_rejection(conn, ledgers):
    """Test that valid tenant token is rejected when missing the required scope."""
    raw_reader, _ = create_capability_token(
        conn=conn,
        role=Role.READER,
        ledger_id="alpha",
    )

    # Read scope -> OK
    PolicyEnforcer.authorize(conn, raw_reader, "ledger:read", "alpha")

    # Write scope -> Rejected
    with pytest.raises(InsufficientScopeError, match="Token lacks required scope: staging:write"):
        PolicyEnforcer.authorize(conn, raw_reader, "staging:write", "alpha")

    # Compile scope -> Rejected
    with pytest.raises(InsufficientScopeError, match="Token lacks required scope: compile:execute"):
        PolicyEnforcer.authorize(conn, raw_reader, "compile:execute", "alpha")


def test_malformed_and_invalid_token_rejection(conn, ledgers):
    """Test that malformed tokens and unregistered tokens fail immediately."""
    # Malformed tokens
    with pytest.raises(MalformedTokenError, match="Malformed bearer token"):
        PolicyEnforcer.authorize(conn, "invalid_prefix_123", "ledger:read", "alpha")

    with pytest.raises(MalformedTokenError, match="Malformed bearer token"):
        PolicyEnforcer.authorize(conn, "il_cap_short", "ledger:read", "alpha")

    with pytest.raises(MalformedTokenError, match="Malformed bearer token"):
        PolicyEnforcer.authorize(conn, "", "ledger:read", "alpha")

    # Unregistered token
    fake_token = "il_cap_" + "f" * 64
    with pytest.raises(InvalidTokenError, match="Invalid capability token"):
        PolicyEnforcer.authorize(conn, fake_token, "ledger:read", "alpha")


def test_token_revocation(conn, ledgers):
    """Test explicit revocation of capability tokens."""
    raw_token, token_obj = create_capability_token(
        conn=conn,
        role=Role.COMPILER,
        ledger_id="alpha",
    )

    # Valid before revocation
    PolicyEnforcer.authorize(conn, raw_token, "compile:execute", "alpha")

    # Revoke token
    revoked = revoke_capability_token(conn, token_obj.token_id)
    assert revoked is True

    # Revoking again returns False
    assert revoke_capability_token(conn, token_obj.token_id) is False

    # Attempt authorization after revocation
    with pytest.raises(TokenRevokedError, match="Capability token has been revoked"):
        PolicyEnforcer.authorize(conn, raw_token, "compile:execute", "alpha")


def test_token_expiration(conn, ledgers):
    """Test expired capability tokens are rejected."""
    past_ts = "2026-09-01T00:00:00Z"
    future_ts = "2026-09-20T00:00:00Z"
    now_ts = "2026-09-10T12:00:00Z"

    # Expired token
    raw_expired, _ = create_capability_token(
        conn=conn,
        role=Role.READER,
        ledger_id="alpha",
        expires_at=past_ts,
    )
    with pytest.raises(TokenExpiredError, match="Capability token has expired"):
        PolicyEnforcer.authorize(conn, raw_expired, "ledger:read", "alpha", now_utc=now_ts)

    # Non-expired token
    raw_valid, _ = create_capability_token(
        conn=conn,
        role=Role.READER,
        ledger_id="alpha",
        expires_at=future_ts,
    )
    authed = PolicyEnforcer.authorize(conn, raw_valid, "ledger:read", "alpha", now_utc=now_ts)
    assert authed.expires_at == future_ts


def test_list_capability_tokens(conn, ledgers):
    """Test listing capability tokens filtered by tenant and revocation status."""
    _, tok_a1 = create_capability_token(conn, Role.READER, "alpha")
    _, tok_a2 = create_capability_token(conn, Role.OPERATOR, "alpha")
    _, tok_b = create_capability_token(conn, Role.COMPILER, "beta")
    _, tok_g = create_capability_token(conn, Role.ADMIN, None, is_global=True)

    revoke_capability_token(conn, tok_a2.token_id)

    # List all tokens for alpha (includes alpha + global)
    alpha_all = list_capability_tokens(conn, ledger_id="alpha", include_revoked=True)
    alpha_ids = {t.token_id for t in alpha_all}
    assert tok_a1.token_id in alpha_ids
    assert tok_a2.token_id in alpha_ids
    assert tok_g.token_id in alpha_ids
    assert tok_b.token_id not in alpha_ids

    # List active only for alpha
    alpha_active = list_capability_tokens(conn, ledger_id="alpha", include_revoked=False)
    alpha_active_ids = {t.token_id for t in alpha_active}
    assert tok_a1.token_id in alpha_active_ids
    assert tok_a2.token_id not in alpha_active_ids
    assert tok_g.token_id in alpha_active_ids
