"""Fenced leader election engine with monotonic terms and randomized fencing tokens."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

DEFAULT_LEASE_SECONDS: Final[int] = 15


class LeaderFencedError(RuntimeError):
    """Raised when a node attempting leadership operations is fenced or unleased."""


@dataclass(frozen=True)
class LeaderLease:
    """Immutable record of an active cluster primary lease."""

    cluster_id: str
    term: int
    leader_node_id: str
    lease_fence_token: str
    lease_acquired_at_utc: str
    lease_expires_at_utc: str

    @property
    def is_expired(self) -> bool:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self.lease_expires_at_utc <= now_utc


class LeaderElectionEngine:
    """Manages term-based leader leases, atomic acquisition, renewal, and fencing assertions."""

    @staticmethod
    def get_current_lease(conn: sqlite3.Connection, cluster_id: str) -> LeaderLease | None:
        """Fetch the current leader lease for a cluster."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT cluster_id, term, leader_node_id, lease_fence_token,
                   lease_acquired_at_utc, lease_expires_at_utc
            FROM cluster_leader_leases
            WHERE cluster_id = ?
            """,
            (cluster_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return LeaderLease(
            cluster_id=row[0],
            term=row[1],
            leader_node_id=row[2],
            lease_fence_token=row[3],
            lease_acquired_at_utc=row[4],
            lease_expires_at_utc=row[5],
        )

    @staticmethod
    def is_leader(
        conn: sqlite3.Connection,
        cluster_id: str,
        node_id: str,
        fence_token: str,
        now_utc: str | None = None,
    ) -> bool:
        """Check if the given node holds an active, unexpired lease with matching fence token."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1 FROM cluster_leader_leases
            WHERE cluster_id = ?
              AND leader_node_id = ?
              AND lease_fence_token = ?
              AND lease_expires_at_utc > ?
            """,
            (cluster_id, node_id, fence_token, now_utc),
        )
        return cursor.fetchone() is not None


    @classmethod
    def assert_leadership(
        cls,
        conn: sqlite3.Connection,
        cluster_id: str,
        node_id: str,
        fence_token: str,
        now_utc: str | None = None,
    ) -> None:
        """Raise LeaderFencedError if the node is not the active, unexpired leader."""
        if not cls.is_leader(conn, cluster_id, node_id, fence_token, now_utc):
            raise LeaderFencedError(
                f"Leadership assertion failed for node '{node_id}' in cluster '{cluster_id}' (fenced or expired)"
            )

    @classmethod
    def acquire_lease(
        cls,
        conn: sqlite3.Connection,
        cluster_id: str,
        candidate_node_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now_utc: str | None = None,
    ) -> LeaderLease:
        """Attempt to acquire a leader lease for candidate node, incrementing term if needed."""
        now = datetime.now(timezone.utc)
        if now_utc is None:
            now_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at_utc = (now + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.cursor()
        current = cls.get_current_lease(conn, cluster_id)

        new_fence_token = uuid.uuid4().hex

        if current is None:
            # First lease
            term = 1
            cursor.execute(
                """
                INSERT INTO cluster_leader_leases (
                    cluster_id, term, leader_node_id, lease_fence_token,
                    lease_acquired_at_utc, lease_expires_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cluster_id, term, candidate_node_id, new_fence_token, now_utc, expires_at_utc),
            )
            return LeaderLease(
                cluster_id=cluster_id,
                term=term,
                leader_node_id=candidate_node_id,
                lease_fence_token=new_fence_token,
                lease_acquired_at_utc=now_utc,
                lease_expires_at_utc=expires_at_utc,
            )

        # Existing lease
        if current.lease_expires_at_utc <= now_utc:
            # Expired lease: advance term and take over
            new_term = current.term + 1
            cursor.execute(
                """
                UPDATE cluster_leader_leases
                SET term = ?,
                    leader_node_id = ?,
                    lease_fence_token = ?,
                    lease_acquired_at_utc = ?,
                    lease_expires_at_utc = ?
                WHERE cluster_id = ?
                  AND term = ?
                  AND lease_expires_at_utc <= ?
                """,
                (
                    new_term,
                    candidate_node_id,
                    new_fence_token,
                    now_utc,
                    expires_at_utc,
                    cluster_id,
                    current.term,
                    now_utc,
                ),
            )
            if cursor.rowcount == 0:
                raise LeaderFencedError("Concurrent lease acquisition conflict")
            return LeaderLease(
                cluster_id=cluster_id,
                term=new_term,
                leader_node_id=candidate_node_id,
                lease_fence_token=new_fence_token,
                lease_acquired_at_utc=now_utc,
                lease_expires_at_utc=expires_at_utc,
            )

        if current.leader_node_id == candidate_node_id:
            # Current leader renewing with new fence token within same term
            cursor.execute(
                """
                UPDATE cluster_leader_leases
                SET lease_fence_token = ?,
                    lease_acquired_at_utc = ?,
                    lease_expires_at_utc = ?
                WHERE cluster_id = ?
                  AND leader_node_id = ?
                  AND term = ?
                """,
                (new_fence_token, now_utc, expires_at_utc, cluster_id, candidate_node_id, current.term),
            )
            return LeaderLease(
                cluster_id=cluster_id,
                term=current.term,
                leader_node_id=candidate_node_id,
                lease_fence_token=new_fence_token,
                lease_acquired_at_utc=now_utc,
                lease_expires_at_utc=expires_at_utc,
            )

        # Active lease held by another node
        raise LeaderFencedError(
            f"Active lease held by node '{current.leader_node_id}' until {current.lease_expires_at_utc}"
        )

    @classmethod
    def renew_lease(
        cls,
        conn: sqlite3.Connection,
        cluster_id: str,
        leader_node_id: str,
        fence_token: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now_utc: str | None = None,
    ) -> LeaderLease:
        """Renew an existing leader lease without changing the fencing token."""
        now = datetime.now(timezone.utc)
        if now_utc is None:
            now_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at_utc = (now + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE cluster_leader_leases
            SET lease_expires_at_utc = ?
            WHERE cluster_id = ?
              AND leader_node_id = ?
              AND lease_fence_token = ?
              AND lease_expires_at_utc >= ?
            """,
            (expires_at_utc, cluster_id, leader_node_id, fence_token, now_utc),
        )
        if cursor.rowcount == 0:
            raise LeaderFencedError(
                f"Failed to renew lease for node '{leader_node_id}' in cluster '{cluster_id}' (fenced or expired)"
            )

        current = cls.get_current_lease(conn, cluster_id)
        if not current:
            raise LeaderFencedError("Lease missing post-renewal")
        return current

    @classmethod
    def step_down(
        cls,
        conn: sqlite3.Connection,
        cluster_id: str,
        leader_node_id: str,
        fence_token: str,
        now_utc: str | None = None,
    ) -> bool:
        """Voluntarily step down as leader by expiring the active lease immediately."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE cluster_leader_leases
            SET lease_expires_at_utc = ?
            WHERE cluster_id = ?
              AND leader_node_id = ?
              AND lease_fence_token = ?
            """,
            (now_utc, cluster_id, leader_node_id, fence_token),
        )
        return cursor.rowcount > 0
