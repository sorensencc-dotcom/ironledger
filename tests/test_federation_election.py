"""Tests for Phase 12 Track 12.1: Leader election, lease fencing, and heartbeat failover."""

from __future__ import annotations

import ast
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ironledger.db.migrations import migrate_governed
from ironledger.federation import (
    HeartbeatMonitor,
    LeaderElectionEngine,
    LeaderFencedError,
    LeaderLease,
    NodeHeartbeatRecord,
)


def test_ast_zero_float_in_federation_modules():
    """Verify zero float operations in federation election and heartbeat modules."""
    fed_dir = Path(__file__).parent.parent / "src" / "ironledger" / "federation"
    files = list(fed_dir.glob("*.py"))
    assert len(files) >= 2, "Expected election.py and heartbeat.py"

    class FloatScanner(ast.NodeVisitor):
        def __init__(self, filename: str):
            self.filename = filename
            self.violations: list[str] = []

        def visit_BinOp(self, node: ast.BinOp):
            if isinstance(node.op, ast.Div):
                self.violations.append(f"{self.filename}:L{node.lineno}: Prohibited float division operator '/'")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("float", "Decimal"):
                self.violations.append(f"{self.filename}:L{node.lineno}: Prohibited float/Decimal call '{node.func.id}()'")
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant):
            if isinstance(node.value, float):
                self.violations.append(f"{self.filename}:L{node.lineno}: Prohibited float literal '{node.value}'")
            self.generic_visit(node)

    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        scanner = FloatScanner(f.name)
        scanner.visit(tree)
        assert not scanner.violations, f"Float violations found in {f.name}: {scanner.violations}"


@pytest.fixture
def election_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    # Seed cluster and nodes
    conn.execute(
        """
        INSERT INTO federation_cluster_nodes (node_id, cluster_id, endpoint_url, role)
        VALUES ('node_1', 'cluster_alpha', 'https://node1.ironledger.net', 'PRIMARY'),
               ('node_2', 'cluster_alpha', 'https://node2.ironledger.net', 'REPLICA')
        """
    )
    conn.commit()
    return conn


def test_leader_election_lifecycle(election_db: sqlite3.Connection):
    conn = election_db

    # 1. Initial lease acquisition by node_1
    lease_1 = LeaderElectionEngine.acquire_lease(
        conn=conn,
        cluster_id="cluster_alpha",
        candidate_node_id="node_1",
        lease_seconds=30,
    )
    assert lease_1.term == 1
    assert lease_1.leader_node_id == "node_1"
    assert len(lease_1.lease_fence_token) >= 16

    # Verify is_leader and assert_leadership
    assert LeaderElectionEngine.is_leader(conn, "cluster_alpha", "node_1", lease_1.lease_fence_token) is True
    LeaderElectionEngine.assert_leadership(conn, "cluster_alpha", "node_1", lease_1.lease_fence_token)

    # 2. Competing candidate node_2 fails while lease active
    with pytest.raises(LeaderFencedError, match="Active lease held by node 'node_1'"):
        LeaderElectionEngine.acquire_lease(
            conn=conn,
            cluster_id="cluster_alpha",
            candidate_node_id="node_2",
            lease_seconds=30,
        )

    # 3. Node_1 renews lease
    renewed = LeaderElectionEngine.renew_lease(
        conn=conn,
        cluster_id="cluster_alpha",
        leader_node_id="node_1",
        fence_token=lease_1.lease_fence_token,
        lease_seconds=60,
    )
    assert renewed.term == 1
    assert renewed.lease_fence_token == lease_1.lease_fence_token

    # 4. Competing node with wrong fence token fails renewal and assertion
    with pytest.raises(LeaderFencedError):
        LeaderElectionEngine.renew_lease(
            conn=conn,
            cluster_id="cluster_alpha",
            leader_node_id="node_1",
            fence_token="invalid_fence_token",
        )

    with pytest.raises(LeaderFencedError):
        LeaderElectionEngine.assert_leadership(
            conn=conn,
            cluster_id="cluster_alpha",
            node_id="node_2",
            fence_token=lease_1.lease_fence_token,
        )

    # 5. Node_1 voluntarily steps down
    step_down_ok = LeaderElectionEngine.step_down(
        conn=conn,
        cluster_id="cluster_alpha",
        leader_node_id="node_1",
        fence_token=lease_1.lease_fence_token,
    )
    assert step_down_ok is True

    # 6. Node_2 acquires lease after step down (term increments to 2)
    lease_2 = LeaderElectionEngine.acquire_lease(
        conn=conn,
        cluster_id="cluster_alpha",
        candidate_node_id="node_2",
        lease_seconds=30,
    )
    assert lease_2.term == 2
    assert lease_2.leader_node_id == "node_2"
    assert lease_2.lease_fence_token != lease_1.lease_fence_token

    # Former leader node_1 write attempt fails
    assert LeaderElectionEngine.is_leader(conn, "cluster_alpha", "node_1", lease_1.lease_fence_token) is False
    with pytest.raises(LeaderFencedError):
        LeaderElectionEngine.assert_leadership(conn, "cluster_alpha", "node_1", lease_1.lease_fence_token)


def test_heartbeat_monitor_and_automatic_promotion(election_db: sqlite3.Connection):
    conn = election_db
    now = datetime.now(timezone.utc)
    t0 = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_t = (now - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Record heartbeat for node_1 (stale) and node_2 (fresh)
    HeartbeatMonitor.record_heartbeat(conn, "node_1", now_utc=stale_t)
    HeartbeatMonitor.record_heartbeat(conn, "node_2", now_utc=t0)
    conn.commit()

    # Query cluster nodes staleness
    nodes = HeartbeatMonitor.get_cluster_nodes(conn, "cluster_alpha", stale_threshold_seconds=15, now_utc=t0)
    assert len(nodes) == 2
    node1_rec = next(n for n in nodes if n.node_id == "node_1")
    node2_rec = next(n for n in nodes if n.node_id == "node_2")
    assert node1_rec.is_stale is True
    assert node2_rec.is_stale is False

    # Check and promote node_2
    promoted, lease = HeartbeatMonitor.check_and_promote(
        conn=conn,
        cluster_id="cluster_alpha",
        candidate_node_id="node_2",
        lease_seconds=30,
        now_utc=t0,
    )
    conn.commit()

    assert promoted is True
    assert lease is not None
    assert lease.leader_node_id == "node_2"
    assert lease.term == 1

    # Verify roles updated in database
    cur = conn.cursor()
    cur.execute("SELECT node_id, role FROM federation_cluster_nodes WHERE cluster_id = 'cluster_alpha' ORDER BY node_id")
    roles = dict(cur.fetchall())
    assert roles["node_1"] == "REPLICA"
    assert roles["node_2"] == "PRIMARY"

    # Verify system alert event emitted into outbox and governance audit
    cur.execute("SELECT COUNT(*) FROM federated_event_outbox WHERE event_type = 'SYSTEM_ALERT'")
    assert cur.fetchone()[0] >= 1
