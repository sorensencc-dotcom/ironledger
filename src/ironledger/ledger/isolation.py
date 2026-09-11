"""Multi-tenant ledger isolation, scoped cryptographic key derivation, and boundary enforcement."""

from __future__ import annotations

import hmac
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, Union


class TenantIsolationError(Exception):
    """Raised when a tenant isolation boundary is violated."""


class BoundaryBreachError(Exception):
    """Raised when a ledger or filesystem boundary is breached."""


def _to_bytes(value: Union[bytes, str]) -> bytes:
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8")


def derive_ledger_key(
    authority_secret: Union[bytes, str],
    tenant_id: str,
    ledger_id: str,
) -> bytes:
    """
    Deterministic ledger-scoped signing key:
    HMAC-SHA256(authority_secret, f"{tenant_id}:{ledger_id}".encode("utf-8"))
    """
    secret = _to_bytes(authority_secret)
    msg = f"{tenant_id}:{ledger_id}".encode("utf-8")
    return hmac.new(secret, msg, sha256).digest()


def derive_tenant_salt(
    master_salt: Union[bytes, str],
    tenant_id: str,
) -> bytes:
    """
    Deterministic tenant-scoped salt:
    HMAC-SHA256(master_salt, tenant_id.encode("utf-8"))
    """
    salt = _to_bytes(master_salt)
    msg = tenant_id.encode("utf-8")
    return hmac.new(salt, msg, sha256).digest()


def assert_tenant_isolation(
    context_tenant: str,
    target_tenant: str,
) -> None:
    """
    Enforce tenant isolation. Wildcards may be allowed if explicitly designed,
    otherwise strict equality.
    """
    if context_tenant == "*":
        # wildcard context: allowed to access any tenant
        return
    if target_tenant == "*":
        # wildcard target: not allowed, ambiguous scope
        raise TenantIsolationError(
            f"Target tenant wildcard not permitted (context={context_tenant})"
        )
    if context_tenant != target_tenant:
        raise TenantIsolationError(
            f"Tenant isolation breach: context={context_tenant}, target={target_tenant}"
        )


def assert_ledger_isolation(
    context_ledger: str,
    target_ledger: str,
) -> None:
    """
    Enforce ledger isolation. Same wildcard semantics as tenant.
    """
    if context_ledger == "*":
        return
    if target_ledger == "*":
        raise BoundaryBreachError(
            f"Target ledger wildcard not permitted (context={context_ledger})"
        )
    if context_ledger != target_ledger:
        raise BoundaryBreachError(
            f"Ledger isolation breach: context={context_ledger}, target={target_ledger}"
        )


def resolve_tenant_ledger_path(
    beancount_root: Union[Path, str],
    tenant_id: str,
    ledger_id: str,
) -> Path:
    """
    Resolve a canonical path for a tenant+ledger under beancount_root.

    Requirements:
    - Confinement to beancount_root.
    - Reject directory traversal (../, absolute paths).
    - Reject symlinks in the resolved path.
    """
    root = Path(beancount_root).resolve()

    # Construct relative path components only
    tenant_component = Path(tenant_id)
    ledger_component = Path(ledger_id)

    # Reject absolute components or paths starting with root separators / drive letters
    if (
        tenant_component.is_absolute()
        or ledger_component.is_absolute()
        or tenant_id.startswith(("/", "\\"))
        or ledger_id.startswith(("/", "\\"))
        or bool(tenant_component.drive)
        or bool(ledger_component.drive)
    ):
        raise BoundaryBreachError("Absolute paths are not allowed for tenant/ledger IDs")

    raw_target = root / tenant_component / ledger_component

    # Confinement: candidate must be under root
    resolved = raw_target.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise BoundaryBreachError(
            f"Path traversal detected: {resolved} escapes root {root}"
        )

    # Symlink checks: reject if any component is a symlink
    current = raw_target
    while True:
        if current.is_symlink() or os.path.islink(current):
            raise BoundaryBreachError(f"Symlink in ledger path: {current}")
        if current == root or current.parent == current:
            break
        current = current.parent

    current = resolved
    while True:
        if current.is_symlink() or os.path.islink(current):
            raise BoundaryBreachError(f"Symlink in ledger path: {current}")
        if current == root or current.parent == current:
            break
        current = current.parent

    return resolved


class CapabilityToken:
    """Capability token descriptor used for isolation and boundary verification."""

    def __init__(
        self,
        tenant_id: str,
        ledger_id: str,
        key_id: str = "",
        principal_id: str = "",
        role: str = "",
        capabilities: tuple[str, ...] = (),
    ) -> None:
        self.tenant_id = tenant_id
        self.ledger_id = ledger_id
        self.key_id = key_id
        self.principal_id = principal_id
        self.role = role
        self.capabilities = capabilities


def verify_ledger_boundary(
    token: Any,
    target_tenant_id: str,
    target_ledger_id: str,
) -> None:
    """
    Ensure the capability token scope matches the target tenant+ledger.

    Any mismatch must fail closed.
    """
    is_global = getattr(token, "is_global", False)
    tenant_id = getattr(token, "tenant_id", None)
    ledger_id = getattr(token, "ledger_id", None)

    if is_global:
        tenant_id = "*"
        ledger_id = "*"
    elif tenant_id is None and ledger_id is not None:
        tenant_id = ledger_id
    elif ledger_id is None and tenant_id is not None:
        ledger_id = tenant_id

    if tenant_id is None or ledger_id is None:
        raise TenantIsolationError("Invalid token: missing tenant_id or ledger_id attribute")

    assert_tenant_isolation(tenant_id, target_tenant_id)
    assert_ledger_isolation(ledger_id, target_ledger_id)

