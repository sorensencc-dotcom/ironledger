"""Exit contract test suite for Phase 12: High-Availability Failover, Replication & Security."""

from __future__ import annotations

import ast
from pathlib import Path
import pytest
import sqlite3

from ironledger.db.migrations import migrate_governed
from ironledger.federation.election import LeaderElectionEngine
from ironledger.federation.heartbeat import HeartbeatMonitor
from ironledger.replication.fabric import WalReplicationFabric
from ironledger.security.key_provider import EnvironmentKeyProvider
from ironledger.security.rotation import TenantKeyRotationEngine


def test_phase12_ast_zero_float_division():
    """Verify zero floating-point division (/) in failover, replication, and security engines."""
    targets = [
        Path("src/ironledger/federation/election.py"),
        Path("src/ironledger/federation/heartbeat.py"),
        Path("src/ironledger/replication/fabric.py"),
        Path("src/ironledger/replication/sync.py"),
        Path("src/ironledger/security/rotation.py"),
        Path("src/ironledger/web/routers/failover.py"),
        Path("src/ironledger/cli/commands/failover.py"),
    ]

    for p in targets:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                pytest.fail(f"Float division (/) detected in {p} at line {node.lineno}")


def test_phase12_zero_beancount_imports():
    """Verify zero runtime import beancount across Phase 12 modules."""
    targets = [
        Path("src/ironledger/federation/election.py"),
        Path("src/ironledger/federation/heartbeat.py"),
        Path("src/ironledger/replication/fabric.py"),
        Path("src/ironledger/replication/sync.py"),
        Path("src/ironledger/security/rotation.py"),
    ]

    for p in targets:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "beancount" not in alias.name, f"Import beancount in {p}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "beancount" not in node.module, f"ImportFrom beancount in {p}"


def test_phase12_full_failover_and_recovery_flow(tmp_path: Path):
    """Verify end-to-end leader election, failover, lease fencing, and heartbeat monitoring."""
    db_file = tmp_path / "e2e_ha.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    # 1. Register cluster nodes
    conn.execute(
        "INSERT INTO federation_cluster_nodes (node_id, cluster_id, endpoint_url, role, is_active, created_at_utc) VALUES ('node-1', 'alpha', 'http://node1:8000', 'PRIMARY', 1, '2026-09-12T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO federation_cluster_nodes (node_id, cluster_id, endpoint_url, role, is_active, created_at_utc) VALUES ('node-2', 'alpha', 'http://node2:8000', 'REPLICA', 1, '2026-09-12T00:00:00Z')"
    )
    conn.commit()

    # 2. Acquire initial primary lease
    lease1 = LeaderElectionEngine.acquire_lease(conn, "alpha", "node-1", lease_seconds=10)
    assert lease1.leader_node_id == "node-1"
    assert lease1.term == 1
    assert LeaderElectionEngine.is_leader(conn, "alpha", "node-1", fence_token=lease1.lease_fence_token) is True

    # 3. Controlled failover: step down node-1, acquire node-2
    stepped_down = LeaderElectionEngine.step_down(conn, "alpha", "node-1", fence_token=lease1.lease_fence_token)
    assert stepped_down is True
    assert LeaderElectionEngine.is_leader(conn, "alpha", "node-1", fence_token=lease1.lease_fence_token) is False

    lease2 = LeaderElectionEngine.acquire_lease(conn, "alpha", "node-2", lease_seconds=10)
    assert lease2.leader_node_id == "node-2"
    assert lease2.term == 2
    assert LeaderElectionEngine.is_leader(conn, "alpha", "node-2", fence_token=lease2.lease_fence_token) is True

    # 4. Heartbeat monitor check
    nodes = HeartbeatMonitor.get_cluster_nodes(conn, "alpha")
    assert len(nodes) == 2
