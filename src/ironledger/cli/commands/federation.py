"""CLI subcommands for multi-tenant federation and outbox dispatch."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ironledger.db.connection import connect
from ironledger.events.dispatcher import OutboxDispatcher
from ironledger.governance.migrations import migrate_governed


def run_federation_nodes_list(db_path: str | Path) -> int:
    """List registered cluster nodes."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT node_id, cluster_id, endpoint_url, role, last_heartbeat_utc, is_active
            FROM federation_cluster_nodes
            ORDER BY cluster_id, node_id
            """
        )
        rows = cursor.fetchall()
        print(f"Registered Cluster Nodes ({len(rows)}):")
        for r in rows:
            active_str = "ACTIVE" if r[5] else "INACTIVE"
            print(f"  - [{r[3]}] {r[0]} (cluster={r[1]}, url={r[2]}, status={active_str}, heartbeat={r[4]})")
        return 0
    finally:
        conn.close()


def run_federation_outbox_list(
    db_path: str | Path,
    tenant_id: str | None = None,
    limit: int = 50,
) -> int:
    """List pending outbox events."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        cursor = conn.cursor()
        query = """
            SELECT seq, event_id, tenant_id, ledger_id, event_type, source, severity,
                   published_to_peers, created_at_utc
            FROM federated_event_outbox
            WHERE published_to_peers = 0
        """
        params: list[Any] = []
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        query += " ORDER BY seq ASC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        print(f"Pending Federated Outbox Events ({len(rows)}):")
        for r in rows:
            print(f"  - #{r[0]}: [{r[6]}] {r[4]} (id={r[1]}, tenant={r[2]}, ledger={r[3]}, src={r[5]})")
        return 0
    finally:
        conn.close()


def run_federation_outbox_dispatch(
    db_path: str | Path,
    worker_id: str = "cli_worker",
    batch_size: int = 50,
) -> int:
    """Claim and simulate local acknowledgment of outbox events."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        fence_token, events = OutboxDispatcher.claim_batch(
            conn, worker_id=worker_id, batch_size=batch_size
        )
        conn.commit()

        if not events:
            print("No pending outbox events to dispatch.")
            return 0

        print(f"Claimed {len(events)} events (fence_token={fence_token[:8]}...).")
        # Acknowledge delivery
        event_ids = [e.event_id for e in events]
        ack_count = OutboxDispatcher.acknowledge_batch(conn, event_ids, fence_token)
        conn.commit()
        print(f"Acknowledged {ack_count} events dispatched.")
        return 0
    finally:
        conn.close()
