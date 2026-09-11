import time
import pytest
from ironledger.rbac.tokens import (
    mint_capability_token,
    verify_capability_token,
    TokenExpiredError,
    TokenSecurityError,
)
from ironledger.rbac.policy import (
    evaluate_action_permission,
    AuthorizationError,
    matches_capability,
)

SECRET = b"test-authority-secret-key-32bytes!!"


def test_mint_and_verify_valid_token():
    token, sig = mint_capability_token(
        secret_key=SECRET,
        token_id="tok_001",
        tenant_id="tenant_a",
        ledger_id="ledger_01",
        principal_id="user_admin",
        role="ADMIN",
        capabilities=["*"],
    )
    assert verify_capability_token(SECRET, token, sig) is True


def test_token_tamper_fails_verification():
    token, sig = mint_capability_token(
        secret_key=SECRET,
        token_id="tok_002",
        tenant_id="tenant_a",
        ledger_id="ledger_01",
        principal_id="user_daemon",
        role="OPERATOR",
        capabilities=["ledger:stage"],
    )
    # Attempt tamper with capabilities
    tampered = token.__class__(
        token_id=token.token_id,
        tenant_id=token.tenant_id,
        ledger_id=token.ledger_id,
        principal_id=token.principal_id,
        role=token.role,
        capabilities=("*",),
        issued_at=token.issued_at,
        expires_at=token.expires_at,
    )
    with pytest.raises(TokenSecurityError):
        verify_capability_token(SECRET, tampered, sig)


def test_expired_token_rejection():
    token, sig = mint_capability_token(
        secret_key=SECRET,
        token_id="tok_003",
        tenant_id="tenant_a",
        ledger_id="ledger_01",
        principal_id="user_daemon",
        role="OPERATOR",
        capabilities=["ledger:stage"],
        ttl_seconds=10,
        now=1000,
    )
    with pytest.raises(TokenExpiredError):
        verify_capability_token(SECRET, token, sig, now=1020)


def test_tenant_boundary_enforcement():
    token, _ = mint_capability_token(
        secret_key=SECRET,
        token_id="tok_004",
        tenant_id="tenant_alpha",
        ledger_id="ledger_main",
        principal_id="auditor_01",
        role="AUDITOR",
        capabilities=["audit:read"],
    )
    with pytest.raises(AuthorizationError, match="Tenant boundary breach"):
        evaluate_action_permission(
            token=token,
            required_capability="audit:read",
            target_tenant_id="tenant_beta",
            target_ledger_id="ledger_main",
        )


def test_scoped_capability_evaluation():
    token, _ = mint_capability_token(
        secret_key=SECRET,
        token_id="tok_005",
        tenant_id="tenant_alpha",
        ledger_id="ledger_main",
        principal_id="ingest_svc",
        role="INGEST_DAEMON",
        capabilities=["ledger:stage"],
    )
    # Allowed capability
    evaluate_action_permission(
        token=token,
        required_capability="ledger:stage",
        target_tenant_id="tenant_alpha",
        target_ledger_id="ledger_main",
    )
    # Denied capability
    with pytest.raises(AuthorizationError, match="denied capability"):
        evaluate_action_permission(
            token=token,
            required_capability="ledger:compile",
            target_tenant_id="tenant_alpha",
            target_ledger_id="ledger_main",
        )
