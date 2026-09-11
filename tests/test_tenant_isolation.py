"""Multi-tenant ledger isolation and cryptographic boundary verification test suite."""

import os
from pathlib import Path

import pytest

from ironledger.ledger import (
    BoundaryBreachError,
    CapabilityToken,
    TenantIsolationError,
    assert_ledger_isolation,
    assert_tenant_isolation,
    derive_ledger_key,
    derive_tenant_salt,
    resolve_tenant_ledger_path,
    verify_ledger_boundary,
)
from ironledger.rbac.tokens import CapabilityToken as RbacCapabilityToken


def test_derive_ledger_key_deterministic():
    secret = b"authority-secret"
    k1 = derive_ledger_key(secret, "tenantA", "ledger1")
    k2 = derive_ledger_key(secret, "tenantA", "ledger1")
    assert k1 == k2


def test_derive_ledger_key_distinct_across_tenants_ledgers():
    secret = b"authority-secret"
    k_tenantA_ledger1 = derive_ledger_key(secret, "tenantA", "ledger1")
    k_tenantA_ledger2 = derive_ledger_key(secret, "tenantA", "ledger2")
    k_tenantB_ledger1 = derive_ledger_key(secret, "tenantB", "ledger1")

    assert k_tenantA_ledger1 != k_tenantA_ledger2
    assert k_tenantA_ledger1 != k_tenantB_ledger1
    assert k_tenantA_ledger2 != k_tenantB_ledger1


def test_derive_tenant_salt_deterministic_and_distinct():
    master = b"master-salt"
    sA1 = derive_tenant_salt(master, "tenantA")
    sA2 = derive_tenant_salt(master, "tenantA")
    sB = derive_tenant_salt(master, "tenantB")

    assert sA1 == sA2
    assert sA1 != sB


def test_assert_tenant_isolation_match():
    assert_tenant_isolation("tenantA", "tenantA")


def test_assert_tenant_isolation_wildcard_context():
    # wildcard context allowed to access any tenant
    assert_tenant_isolation("*", "tenantA")
    assert_tenant_isolation("*", "tenantB")


def test_assert_tenant_isolation_mismatch_raises():
    with pytest.raises(TenantIsolationError):
        assert_tenant_isolation("tenantA", "tenantB")


def test_assert_tenant_isolation_target_wildcard_raises():
    with pytest.raises(TenantIsolationError):
        assert_tenant_isolation("tenantA", "*")


def test_assert_ledger_isolation_match():
    assert_ledger_isolation("ledger1", "ledger1")


def test_assert_ledger_isolation_wildcard_context():
    assert_ledger_isolation("*", "ledger1")


def test_assert_ledger_isolation_mismatch_raises():
    with pytest.raises(BoundaryBreachError):
        assert_ledger_isolation("ledger1", "ledger2")


def test_assert_ledger_isolation_target_wildcard_raises():
    with pytest.raises(BoundaryBreachError):
        assert_ledger_isolation("ledger1", "*")


def test_resolve_tenant_ledger_path_confined(tmp_path):
    root = tmp_path / "beancount_root"
    root.mkdir(exist_ok=True)
    path = resolve_tenant_ledger_path(root, "tenantA", "ledger1")
    assert path.is_relative_to(root.resolve())


def test_resolve_tenant_ledger_path_rejects_absolute(tmp_path):
    root = tmp_path / "beancount_root"
    root.mkdir(exist_ok=True)
    with pytest.raises(BoundaryBreachError):
        resolve_tenant_ledger_path(root, "/etc/passwd", "ledger1")


def test_resolve_tenant_ledger_path_rejects_traversal(tmp_path):
    root = tmp_path / "beancount_root"
    root.mkdir(exist_ok=True)
    with pytest.raises(BoundaryBreachError):
        resolve_tenant_ledger_path(root, "..", "ledger1")


def test_resolve_tenant_ledger_path_rejects_internal_traversal(tmp_path):
    root = tmp_path / "beancount_root"
    root.mkdir(exist_ok=True)
    with pytest.raises(BoundaryBreachError):
        resolve_tenant_ledger_path(root, "tenantA/../tenantB", "ledger1")
    with pytest.raises(BoundaryBreachError):
        resolve_tenant_ledger_path(root, "tenantA", "ledger1/../ledger2")


def test_resolve_tenant_ledger_path_rejects_symlink(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    tenant_dir = root / "tenantA"
    tenant_dir.mkdir()
    ledger_dir = tenant_dir / "ledger1"
    ledger_dir.mkdir()
    # introduce symlink in path
    symlink = tenant_dir / "link"
    try:
        symlink.symlink_to(ledger_dir)
        with pytest.raises(BoundaryBreachError):
            resolve_tenant_ledger_path(root, "tenantA/link", "anything")
    except (OSError, NotImplementedError):
        # Fallback when symlink creation is not permitted on host platform
        with pytest.raises(BoundaryBreachError):
            resolve_tenant_ledger_path(root, "tenantA/../../escape", "anything")


def test_resolve_tenant_ledger_path_rejects_symlink_root(tmp_path):
    real_root = tmp_path / "real_root"
    real_root.mkdir()
    symlink_root = tmp_path / "symlink_root"
    try:
        symlink_root.symlink_to(real_root)
        with pytest.raises(BoundaryBreachError):
            resolve_tenant_ledger_path(symlink_root, "tenantA", "ledger1")
    except (OSError, NotImplementedError):
        # Symlink creation not supported in unprivileged Windows mode
        pass



def test_verify_ledger_boundary_scope_match():
    token = CapabilityToken("tenantA", "ledger1", "key1")
    verify_ledger_boundary(token, "tenantA", "ledger1")


def test_verify_ledger_boundary_tenant_mismatch_fails_closed():
    token = CapabilityToken("tenantA", "ledger1", "key1")
    with pytest.raises(TenantIsolationError):
        verify_ledger_boundary(token, "tenantB", "ledger1")


def test_verify_ledger_boundary_ledger_mismatch_fails_closed():
    token = CapabilityToken("tenantA", "ledger1", "key1")
    with pytest.raises(BoundaryBreachError):
        verify_ledger_boundary(token, "tenantA", "ledger2")


def test_verify_ledger_boundary_rbac_token_compatibility():
    rbac_token = RbacCapabilityToken(
        token_id="tok_123",
        tenant_id="tenant_gamma",
        ledger_id="ledger_primary",
        principal_id="user_admin",
        role="ADMIN",
        capabilities=("*",),
        issued_at=1000,
        expires_at=2000,
    )
    verify_ledger_boundary(rbac_token, "tenant_gamma", "ledger_primary")

    with pytest.raises(TenantIsolationError):
        verify_ledger_boundary(rbac_token, "tenant_other", "ledger_primary")

    with pytest.raises(BoundaryBreachError):
        verify_ledger_boundary(rbac_token, "tenant_gamma", "ledger_secondary")
