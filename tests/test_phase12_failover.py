"""Integration tests for Phase 12: High-Availability Failover, WAL Replication & Key Rotation."""

from __future__ import annotations

import os
import sqlite3
import struct
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from ironledger.db.migrations import migrate_governed
from ironledger.federation.election import LeaderElectionEngine, LeaderFencedError
from ironledger.federation.heartbeat import HeartbeatMonitor
from ironledger.replication.fabric import WalReplicationFabric
from ironledger.replication.sync import DivergenceDetectedError, ReplicationSynchronizer
from ironledger.replication.wal_parser import (
    WAL_MAGIC_LE,
    _compute_wal_checksum,
    parse_wal_frames,
    parse_wal_header,
)
from ironledger.security.envelope import EnvelopeCiphertext, EnvelopeEncryptor
from ironledger.security.key_provider import EnvironmentKeyProvider
from ironledger.security.rotation import TenantKeyRotationEngine
from ironledger.web.app import create_app


def _build_wal_bytes(page_size: int = 512, frame_count: int = 2) -> bytes:
    magic = WAL_MAGIC_LE
    version = 3007000
    seq = 1
    salt1 = 0x12345678
    salt2 = 0x87654321
    header_prefix = struct.pack(">IIIIII", magic, version, page_size, seq, salt1, salt2)
    c1, c2 = _compute_wal_checksum(header_prefix, is_big_endian=False)
    header_bytes = header_prefix + struct.pack(">II", c1, c2)

    running_s1 = c1
    running_s2 = c2
    frames_bytes = b""
    for i in range(1, frame_count + 1):
        page_data = bytes([i % 256]) * page_size
        is_commit = (i == frame_count)
        commit_pages = frame_count if is_commit else 0
        f_prefix = struct.pack(">II", i, commit_pages)
        chk_s1, chk_s2 = _compute_wal_checksum(f_prefix, is_big_endian=False, s1_init=running_s1, s2_init=running_s2)
        chk_s1, chk_s2 = _compute_wal_checksum(page_data, is_big_endian=False, s1_init=chk_s1, s2_init=chk_s2)
        f_hdr = f_prefix + struct.pack(">IIII", salt1, salt2, chk_s1, chk_s2)
        frames_bytes += f_hdr + page_data
        running_s1 = chk_s1
        running_s2 = chk_s2

    return header_bytes + frames_bytes


@pytest.fixture
def failover_db(tmp_path: Path):
    db_file = tmp_path / "failover_test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    # Seed nodes and tenant
    conn.execute(
        """
        INSERT INTO federation_cluster_nodes (node_id, cluster_id, endpoint_url, role, is_active, created_at_utc)
        VALUES ('node-primary', 'test-cluster', 'http://127.0.0.1:8000', 'PRIMARY', 1, '2026-09-12T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO federation_cluster_nodes (node_id, cluster_id, endpoint_url, role, is_active, created_at_utc)
        VALUES ('node-replica-1', 'test-cluster', 'http://127.0.0.1:8001', 'REPLICA', 1, '2026-09-12T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO federation_tenants (tenant_id, name, default_ledger_id, is_active, created_at_utc)
        VALUES ('tenant-acme', 'Acme Corp', 'default', 1, '2026-09-12T00:00:00Z')
        """
    )
    conn.commit()
    return conn, db_file


def test_wal_replication_packaging_and_checkpoints(failover_db):
    conn, _ = failover_db
    wal_bytes = _build_wal_bytes(page_size=512, frame_count=3)

    bundle = WalReplicationFabric.package_wal_bundle(
        cluster_id="test-cluster",
        node_id="node-primary",
        wal_bytes=wal_bytes,
        max_frames=10,
    )

    assert bundle.cluster_id == "test-cluster"
    assert bundle.frame_count == 3
    assert bundle.salt1 == 0x12345678
    assert bundle.salt2 == 0x87654321

    recorded = WalReplicationFabric.verify_and_record_checkpoint(conn, bundle)
    assert recorded is True
    conn.commit()

    chk = ReplicationSynchronizer.get_latest_checkpoint(conn, "test-cluster", "node-primary")
    assert chk is not None
    assert chk["frame_count"] == 3
    assert chk["checkpoint_sha256"] == bundle.checkpoint_sha256


def test_wal_replication_divergence_detection():
    chk_primary = {
        "cluster_id": "c1",
        "node_id": "n1",
        "wal_offset_bytes": 2048,
        "salt1": 100,
        "salt2": 200,
        "checkpoint_sha256": "hash_aaa",
    }
    chk_replica_good = {
        "cluster_id": "c1",
        "node_id": "n2",
        "wal_offset_bytes": 2048,
        "salt1": 100,
        "salt2": 200,
        "checkpoint_sha256": "hash_aaa",
    }
    chk_replica_salt_diverge = {
        "cluster_id": "c1",
        "node_id": "n2",
        "wal_offset_bytes": 2048,
        "salt1": 999,
        "salt2": 200,
        "checkpoint_sha256": "hash_aaa",
    }
    chk_replica_hash_diverge = {
        "cluster_id": "c1",
        "node_id": "n2",
        "wal_offset_bytes": 2048,
        "salt1": 100,
        "salt2": 200,
        "checkpoint_sha256": "hash_bbb",
    }

    # Integrity pass
    ReplicationSynchronizer.assert_sync_integrity(chk_primary, chk_replica_good)

    # Salt mismatch throws
    with pytest.raises(DivergenceDetectedError, match="Salt mismatch"):
        ReplicationSynchronizer.assert_sync_integrity(chk_primary, chk_replica_salt_diverge)

    # SHA mismatch throws
    with pytest.raises(DivergenceDetectedError, match="SHA-256 mismatch"):
        ReplicationSynchronizer.assert_sync_integrity(chk_primary, chk_replica_hash_diverge)


def test_zero_downtime_tenant_key_rotation(failover_db, monkeypatch):
    conn, _ = failover_db
    key1 = b"\x01" * 32
    key2 = b"\x02" * 32

    key_provider = EnvironmentKeyProvider()
    key_provider.rotate_key("kek_v1", key1)
    key_provider.rotate_key("kek_v2", key2)

    # Encrypt secret under kek_v1 with AAD
    aad = b"default:webhook:sub_01"
    envelope = EnvelopeEncryptor.encrypt(
        payload=b"webhook_secret_key_12345",
        key_provider=key_provider,
        kek_key_id="kek_v1",
        aad=aad,
    )

    conn.execute(
        """
        INSERT INTO webhook_subscriptions (
            ledger_id, subscription_id, target_url, kek_key_id,
            encrypted_dek_blob, dek_iv_hex, dek_auth_tag_hex,
            encrypted_secret_blob, secret_iv_hex, secret_auth_tag_hex,
            secret_fingerprint_hex, event_types_json, is_active, created_at_utc
        ) VALUES (
            'default', 'sub_01', 'https://example.com/webhook', 'kek_v1',
            ?, ?, ?,
            ?, ?, ?,
            ?, '["ledger.compiled"]', 1, '2026-09-12 00:00:00.000000'
        )
        """,
        (
            envelope.encrypted_dek_blob,
            envelope.dek_iv_hex,
            envelope.dek_auth_tag_hex,
            envelope.encrypted_payload_blob,
            envelope.payload_iv_hex,
            envelope.payload_auth_tag_hex,
            "0" * 64,
        ),
    )
    conn.commit()

    result = TenantKeyRotationEngine.rotate_tenant_kek(
        conn=conn,
        tenant_id="tenant-acme",
        new_kek_key_id="kek_v2",
        rotated_by="operator-alice",
        key_provider=key_provider,
    )

    assert result["status"] == "COMPLETED"
    assert result["rewrapped_count"] == 1
    assert result["new_kek_key_id"] == "kek_v2"

    assert result["new_kek_key_id"] == "kek_v2"

    # Check that rotation history is recorded
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_key_rotations WHERE tenant_id = 'tenant-acme'")
    rot_row = cur.fetchone()
    assert rot_row is not None
