"""Cross-region WAL replication fabric with Merkle-anchored frame checkpoints."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ironledger.events.router import EventRouter
from ironledger.replication.wal_parser import WalHeader, parse_wal_frames


@dataclass(frozen=True)
class WalBundle:
    """Packaged WAL replication payload with cryptographic checkpoint metadata."""

    bundle_id: str
    cluster_id: str
    node_id: str
    start_offset: int
    end_offset: int
    frame_count: int
    salt1: int
    salt2: int
    checkpoint_sha256: str
    frames_bytes: bytes


class WalReplicationFabric:
    """Packages and verifies WAL frame bundles for cross-region replication."""

    @staticmethod
    def package_wal_bundle(
        cluster_id: str,
        node_id: str,
        wal_bytes: bytes,
        max_frames: int = 100,
    ) -> WalBundle:
        """Parse SQLite WAL bytes and package verified frames with checkpoint hash."""
        header, frames = parse_wal_frames(wal_bytes)
        selected_frames = frames[:max_frames]
        frame_count = len(selected_frames)

        frame_payload_sha = hashlib.sha256()
        for f in selected_frames:
            frame_payload_sha.update(f.page_data_sha256.encode("utf-8"))
            frame_payload_sha.update(str(f.page_number).encode("utf-8"))

        checkpoint_sha256 = frame_payload_sha.hexdigest()
        bundle_id = f"wal_bnd_{uuid.uuid4().hex[:16]}"
        end_offset = len(wal_bytes)

        return WalBundle(
            bundle_id=bundle_id,
            cluster_id=cluster_id,
            node_id=node_id,
            start_offset=0,
            end_offset=end_offset,
            frame_count=frame_count,
            salt1=header.salt1,
            salt2=header.salt2,
            checkpoint_sha256=checkpoint_sha256,
            frames_bytes=wal_bytes,
        )

    @staticmethod
    def verify_and_record_checkpoint(
        conn: sqlite3.Connection,
        bundle: WalBundle,
    ) -> bool:
        """Verify WAL bundle integrity and persist replication checkpoint in database."""
        header, frames = parse_wal_frames(bundle.frames_bytes)
        if header.salt1 != bundle.salt1 or header.salt2 != bundle.salt2:
            return False

        # Verify frame count and checkpoint hash
        selected_frames = frames[: bundle.frame_count]
        frame_payload_sha = hashlib.sha256()
        for f in selected_frames:
            frame_payload_sha.update(f.page_data_sha256.encode("utf-8"))
            frame_payload_sha.update(str(f.page_number).encode("utf-8"))

        if frame_payload_sha.hexdigest() != bundle.checkpoint_sha256:
            return False

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        checkpoint_id = f"chk_{uuid.uuid4().hex[:16]}"

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO replication_wal_checkpoints (
                checkpoint_id, cluster_id, node_id, wal_offset_bytes,
                frame_count, salt1, salt2, checkpoint_sha256, synced_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_id,
                bundle.cluster_id,
                bundle.node_id,
                bundle.end_offset,
                bundle.frame_count,
                bundle.salt1,
                bundle.salt2,
                bundle.checkpoint_sha256,
                now_utc,
            ),
        )

        # Emit replication event
        EventRouter.emit_replication_advanced(
            conn=conn,
            ledger_id="default",
            wal_magic=hex(header.magic),
            frame_index=bundle.frame_count,
            commit_page_count=frames[-1].commit_page_count if frames else 0,
        )

        return True
