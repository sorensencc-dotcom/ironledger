"""Phase 2a: verify_manifest rejects manifest-supplied table names it cannot verify.

The manifest string is untrusted input. Its row_counts keys must be checked
against sqlite_master before any count query interpolates them.

The manifest self-hash is content-derived, not a keyed MAC: an attacker who
crafts a malicious row_counts map can recompute a matching self-hash. These
tests therefore build a *validly self-signed* manifest whose row_counts names a
table that does not exist, which is the payload the allowlist must reject before
the count query interpolates the name.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace as dataclass_replace

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.manifests import (
    ManifestVerificationError,
    compute_manifest_digest,
    generate_projection_manifest,
    render_manifest,
    verify_manifest,
)


@pytest.fixture
def empty_db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _manifest_text_with_bad_table(empty_db: sqlite3.Connection, bad_name: str) -> str:
    """Return a rendered, correctly self-signed manifest whose row_counts names ``bad_name``."""
    manifest = generate_projection_manifest(empty_db, created_ts_utc="2026-09-02T10:00:00Z")
    bad_counts = dict(manifest.row_counts or {})
    bad_counts[bad_name] = 0
    tampered = dataclass_replace(manifest, row_counts=bad_counts)
    signed = dataclass_replace(tampered, manifest_self_hash=compute_manifest_digest(tampered))
    return render_manifest(signed)


def test_unknown_table_name_fails_verification(empty_db: sqlite3.Connection):
    text = _manifest_text_with_bad_table(empty_db, "no_such_table")
    with pytest.raises(ManifestVerificationError):
        verify_manifest(text, conn=empty_db)


def test_injection_payload_table_name_fails_verification(empty_db: sqlite3.Connection):
    text = _manifest_text_with_bad_table(empty_db, "x); DROP TABLE audit_events; --")
    with pytest.raises(ManifestVerificationError):
        verify_manifest(text, conn=empty_db)
    # The audit_events table is still present.
    names = {n for (n,) in empty_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "audit_events" in names
