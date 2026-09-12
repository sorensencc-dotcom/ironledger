"""Heartbeat tracking and automated replica promotion monitor."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from ironledger.events.router import EventRouter
from ironledger.federation.election import (
    DEFAULT_LEASE_SECONDS,
    LeaderElectionEngine,
    LeaderFencedError,
    LeaderLease,
)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS: Final[int] = 5
DEFAULT_STALE_THRESHOLD_SECONDS: Final[int] = 15


@dataclass(frozen=True)
class NodeHeartbeatRecord:
    """Status record of a cluster node with heartbeat metrics."""

    node_id: str
    cluster_id: str
    endpoint_url: str
    role: str
    last_heartbeat_utc: str | None
    is_active: bool
    is_stale: bool


class HeartbeatMonitor:
    """Manages node heartbeats, stale node detection, and automatic primary failover promotion."""

    @staticmethod
    def record_heartbeat(
        conn: sqlite3.Connection,
        node_id: str,
        now_utc: str | None = None,
    ) -> bool:
        """Update the heartbeat timestamp for a registered cluster node."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE federation_cluster_nodes
            SET last_heartbeat_utc = ?
            WHERE node_id = ?
            """,
            (now_utc, node_id),
        )
        return cursor.rowcount > 0

    @staticmethod
    def get_cluster_nodes(
        conn: sqlite3.Connection,
        cluster_id: str,
        stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
        now_utc: str | None = None,
    ) -> list[NodeHeartbeatRecord]:
        """Fetch all registered nodes for a cluster with computed staleness status."""
        now = datetime.now(timezone.utc)
        if now_utc is None:
            now_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_cutoff = (now - timedelta(seconds=stale_threshold_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT node_id, cluster_id, endpoint_url, role, last_heartbeat_utc, is_active
            FROM federation_cluster_nodes
            WHERE cluster_id = ?
            ORDER BY node_id ASC
            """,
            (cluster_id,),
        )
        records: list[NodeHeartbeatRecord] = []
        for r in cursor.fetchall():
            node_id, c_id, endpoint, role, last_hb, is_active = r
            is_stale = bool(last_hb is None or last_hb < stale_cutoff)
            records.append(
                NodeHeartbeatRecord(
                    node_id=node_id,
                    cluster_id=c_id,
                    endpoint_url=endpoint,
                    role=role,
                    last_heartbeat_utc=last_hb,
                    is_active=bool(is_active),
                    is_stale=is_stale,
                )
            )
        return records

    @classmethod
    def check_and_promote(
        cls,
        conn: sqlite3.Connection,
        cluster_id: str,
        candidate_node_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now_utc: str | None = None,
    ) -> tuple[bool, LeaderLease | None]:
        """Attempt to promote a candidate node to PRIMARY if current primary is stale or unleased."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            lease = LeaderElectionEngine.acquire_lease(
                conn=conn,
                cluster_id=cluster_id,
                candidate_node_id=candidate_node_id,
                lease_seconds=lease_seconds,
                now_utc=now_utc,
            )
        except LeaderFencedError:
            return False, None

        cursor = conn.cursor()
        # Demote previous primary nodes in cluster
        cursor.execute(
            """
            UPDATE federation_cluster_nodes
            SET role = 'REPLICA'
            WHERE cluster_id = ?
              AND role = 'PRIMARY'
              AND node_id != ?
            """,
            (cluster_id, candidate_node_id),
        )

        # Promote candidate to PRIMARY
        cursor.execute(
            """
            UPDATE federation_cluster_nodes
            SET role = 'PRIMARY',
                last_heartbeat_utc = ?
            WHERE cluster_id = ?
              AND node_id = ?
            """,
            (now_utc, cluster_id, candidate_node_id),
        )

        # Emit governance event
        EventRouter.emit_system_alert(
            conn=conn,
            ledger_id="default",
            severity="WARN",
            message=f"Node '{candidate_node_id}' promoted to PRIMARY for cluster '{cluster_id}' (term {lease.term})",
            details={
                "cluster_id": cluster_id,
                "promoted_node_id": candidate_node_id,
                "term": lease.term,
                "fence_token": lease.lease_fence_token,
                "lease_expires_at_utc": lease.lease_expires_at_utc,
            },
        )

        return True, lease
