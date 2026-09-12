"""CLI subcommands for failover status, primary promotion, and tenant key rotation."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from ironledger.db.connection import connect
from ironledger.federation.election import LeaderElectionEngine
from ironledger.federation.heartbeat import HeartbeatMonitor
from ironledger.governance.migrations import migrate_governed
from ironledger.security.rotation import TenantKeyRotationEngine


def run_failover_status(db_path: str | Path, cluster_id: str = "default") -> int:
    """Display cluster quorum status, active primary lease, and node heartbeats."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        lease = LeaderElectionEngine.get_current_lease(conn, cluster_id)
        nodes = HeartbeatMonitor.get_cluster_nodes(conn, cluster_id)

        total_nodes = len(nodes)
        active_nodes = len([n for n in nodes if n.is_active and not n.is_stale])
        has_quorum = active_nodes >= (total_nodes // 2 + 1) if total_nodes > 0 else False

        print(f"Cluster '{cluster_id}' Failover Status:")
        print(f"  Quorum: {'YES' if has_quorum else 'NO'} ({active_nodes}/{total_nodes} active nodes)")
        if lease:
            exp_str = "EXPIRED" if lease.is_expired else "ACTIVE"
            print(f"  Primary Lease: {lease.leader_node_id} (term {lease.term}, status {exp_str}, expires {lease.lease_expires_at_utc})")
            print(f"  Fence Token: {lease.lease_fence_token}")
        else:
            print("  Primary Lease: None (unassigned)")

        print("  Nodes:")
        for n in nodes:
            stale_str = "STALE" if n.is_stale else "HEALTHY"
            print(f"    - [{n.role}] {n.node_id} ({n.endpoint_url}, status={stale_str}, heartbeat={n.last_heartbeat_utc})")

        return 0
    finally:
        conn.close()


def run_failover_promote(
    db_path: str | Path,
    cluster_id: str,
    candidate_node_id: str,
    lease_seconds: int = 15,
) -> int:
    """Promote a candidate node to cluster PRIMARY."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        promoted, lease = HeartbeatMonitor.check_and_promote(
            conn=conn,
            cluster_id=cluster_id,
            candidate_node_id=candidate_node_id,
            lease_seconds=lease_seconds,
        )
        conn.commit()
        if not promoted or lease is None:
            print(f"ERROR: Promotion failed for node '{candidate_node_id}' in cluster '{cluster_id}' (active lease exists)", file=sys.stderr)
            return 1

        print(f"SUCCESS: Node '{candidate_node_id}' promoted to PRIMARY for cluster '{cluster_id}'")
        print(f"  Term: {lease.term}")
        print(f"  Fence Token: {lease.lease_fence_token}")
        print(f"  Lease Expires: {lease.lease_expires_at_utc}")
        return 0
    finally:
        conn.close()


def run_security_rotate_key(
    db_path: str | Path,
    tenant_id: str,
    new_kek_key_id: str,
    rotated_by: str = "operator",
) -> int:
    """Execute zero-downtime tenant KEK rotation and re-wrap secrets."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        res = TenantKeyRotationEngine.rotate_tenant_kek(
            conn=conn,
            tenant_id=tenant_id,
            new_kek_key_id=new_kek_key_id,
            rotated_by=rotated_by,
        )
        print(f"SUCCESS: Rotated KEK for tenant '{tenant_id}'")
        print(f"  Rotation ID: {res['rotation_id']}")
        print(f"  New KEK: {res['new_kek_key_id']}")
        print(f"  Previous KEK: {res['previous_kek_key_id']}")
        print(f"  Secrets Re-wrapped: {res['rewrapped_count']}")
        print(f"  Completed At: {res['completed_at_utc']}")
        return 0
    finally:
        conn.close()
