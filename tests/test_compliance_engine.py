"""Tests for compliance audit engine, RFC 6962 Merkle tree, and sealed archive bundles."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ironledger.compliance.bundle import (
    ComplianceBundleError,
    generate_compliance_bundle,
    verify_compliance_bundle,
)
from ironledger.compliance.merkle import (
    EMPTY_TREE_ROOT,
    MerkleTree,
    hash_internal,
    hash_leaf,
    verify_inclusion_proof,
)
from ironledger.governance.migrations import migrate_governed


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test_compliance.db"
    connection = sqlite3.connect(db_path)
    migrate_governed(connection, db_path)
    try:
        yield connection
    finally:
        connection.close()


def test_merkle_tree_empty():
    tree = MerkleTree([])
    assert tree.leaf_count == 0
    assert tree.root_hex == EMPTY_TREE_ROOT


def test_merkle_tree_single_leaf():
    payload = b"test payload"
    tree = MerkleTree([payload])
    expected_leaf = hash_leaf(payload)
    assert tree.leaf_count == 1
    assert tree.root_hex == expected_leaf.hex()


def test_merkle_tree_balanced_and_proof():
    leaves = [b"leaf_1", b"leaf_2", b"leaf_3", b"leaf_4"]
    tree = MerkleTree(leaves)
    assert tree.leaf_count == 4

    # Verify inclusion proof for each leaf
    for i, leaf in enumerate(leaves):
        proof = tree.get_proof(i)
        assert verify_inclusion_proof(leaf, proof, tree.root_hex) is True


def test_merkle_tree_odd_leaf_promotion():
    leaves = [b"leaf_1", b"leaf_2", b"leaf_3"]
    tree = MerkleTree(leaves)
    assert tree.leaf_count == 3

    # Hand-calculate expected root with odd promotion
    h1 = hash_leaf(b"leaf_1")
    h2 = hash_leaf(b"leaf_2")
    h3 = hash_leaf(b"leaf_3")
    h12 = hash_internal(h1, h2)
    # h3 promoted to next level
    expected_root = hash_internal(h12, h3).hex()
    assert tree.root_hex == expected_root

    # Proofs
    for i, leaf in enumerate(leaves):
        proof = tree.get_proof(i)
        assert verify_inclusion_proof(leaf, proof, tree.root_hex) is True


def test_generate_and_verify_compliance_bundle(conn: sqlite3.Connection, tmp_path: Path):
    # Setup ledger
    conn.execute(
        "INSERT INTO ledgers (ledger_id, name, base_currency) VALUES (?, ?, ?)",
        ("ledger_corp", "Corporate Ledger", "USD"),
    )

    # Insert governance audit events
    now_utc = "2026-06-01T12:00:00Z"
    conn.execute(
        """
        INSERT INTO governance_audit_events (
            ledger_id, actor, action, target, before_state_json, after_state_json,
            envelope_hash, timestamp_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ledger_corp",
            "operator",
            "UPDATE_POLICY",
            "policy:rate_limit",
            json.dumps({"max": 100}),
            json.dumps({"max": 200}),
            "a" * 64,
            now_utc,
        ),
    )
    conn.commit()

    # Generate bundle
    result = generate_compliance_bundle(
        conn=conn,
        ledger_id="ledger_corp",
        framework="SOC2_TYPE2",
        period_start_utc="2026-01-01T00:00:00Z",
        period_end_utc="2026-12-31T23:59:59Z",
        output_dir=tmp_path,
    )

    assert result.ledger_id == "ledger_corp"
    assert result.framework == "SOC2_TYPE2"
    assert result.record_count >= 1
    assert len(result.merkle_root_hex) == 64
    assert len(result.sealed_archive_sha256) == 64

    # Verify archive file on disk
    archive_file = tmp_path / f"compliance_bundle_ledger_corp_{result.bundle_id}.tar"
    assert archive_file.is_file()

    # Cryptographically verify the bundle
    verify_res = verify_compliance_bundle(
        archive_bytes=result.archive_bytes,
        expected_merkle_root=result.merkle_root_hex,
        expected_sha256=result.sealed_archive_sha256,
    )
    assert verify_res["is_valid"] is True
    assert verify_res["record_count"] == result.record_count


def test_tampered_bundle_fails_verification(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO ledgers (ledger_id, name, base_currency) VALUES (?, ?, ?)",
        ("ledger_sec", "Security Ledger", "USD"),
    )
    conn.commit()

    result = generate_compliance_bundle(
        conn=conn,
        ledger_id="ledger_sec",
        framework="ISO27001",
        period_start_utc="2026-01-01T00:00:00Z",
        period_end_utc="2026-12-31T23:59:59Z",
    )

    # Corrupt a byte in the archive
    tampered_bytes = bytearray(result.archive_bytes)
    tampered_bytes[50] ^= 0xFF

    with pytest.raises(ComplianceBundleError):
        verify_compliance_bundle(
            archive_bytes=bytes(tampered_bytes),
            expected_sha256=result.sealed_archive_sha256,
        )


def test_malicious_path_traversal_in_archive_rejected():
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        data = b'{"bundle_id": "evil"}'
        ti = tarfile.TarInfo(name="../evil.txt")
        ti.size = len(data)
        tar.addfile(ti, io.BytesIO(data))

    with pytest.raises(ComplianceBundleError, match="Hostile archive member"):
        verify_compliance_bundle(tar_buf.getvalue())
