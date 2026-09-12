"""Cross-region state synchronization and WAL divergence detector."""

from __future__ import annotations

import sqlite3
from typing import Any


class DivergenceDetectedError(ValueError):
    """Raised when replica WAL stream diverges from primary cluster stream."""


class ReplicationSynchronizer:
    """Detects WAL stream divergence and manages cross-region sync state."""

    @staticmethod
    def assert_sync_integrity(
        primary_checkpoint: dict[str, Any],
        replica_checkpoint: dict[str, Any],
    ) -> None:
        """Verify that replica WAL checkpoint matches primary on salts and commit hash."""
        p_salt1 = primary_checkpoint.get("salt1")
        p_salt2 = primary_checkpoint.get("salt2")
        r_salt1 = replica_checkpoint.get("salt1")
        r_salt2 = replica_checkpoint.get("salt2")

        if p_salt1 != r_salt1 or p_salt2 != r_salt2:
            raise DivergenceDetectedError(
                f"Salt mismatch between primary ({p_salt1}, {p_salt2}) and replica ({r_salt1}, {r_salt2})"
            )

        p_offset = primary_checkpoint.get("wal_offset_bytes", 0)
        r_offset = replica_checkpoint.get("wal_offset_bytes", 0)
        if p_offset == r_offset and primary_checkpoint.get("checkpoint_sha256") != replica_checkpoint.get("checkpoint_sha256"):
            raise DivergenceDetectedError(
                f"WAL checkpoint SHA-256 mismatch at offset {p_offset}"
            )

    @staticmethod
    def get_latest_checkpoint(
        conn: sqlite3.Connection,
        cluster_id: str,
        node_id: str,
    ) -> dict[str, Any] | None:
        """Fetch the latest WAL replication checkpoint for a given node."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT checkpoint_id, cluster_id, node_id, wal_offset_bytes,
                   frame_count, salt1, salt2, checkpoint_sha256, synced_at_utc
            FROM replication_wal_checkpoints
            WHERE cluster_id = ? AND node_id = ?
            ORDER BY wal_offset_bytes DESC, synced_at_utc DESC
            LIMIT 1
            """,
            (cluster_id, node_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "checkpoint_id": row[0],
            "cluster_id": row[1],
            "node_id": row[2],
            "wal_offset_bytes": row[3],
            "frame_count": row[4],
            "salt1": row[5],
            "salt2": row[6],
            "checkpoint_sha256": row[7],
            "synced_at_utc": row[8],
        }
