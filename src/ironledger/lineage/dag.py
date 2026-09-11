"""Lineage DAG engine with insertion-time cycle prevention."""

from __future__ import annotations

import json
import sqlite3

from ironledger.lineage.models import (
    LineageCycleError,
    LineageEdge,
    LineageNode,
    LineageNodeNotFoundError,
    RelationshipType,
)


class LineageDAG:
    """Manages lineage graph mutations, acyclicity enforcement, and tenant boundaries."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._conn = conn

    def _get_connection(self, conn: sqlite3.Connection | None) -> sqlite3.Connection:
        active_conn = conn if conn is not None else self._conn
        if active_conn is None:
            raise ValueError("No database connection provided")
        return active_conn

    def add_node(
        self,
        node: LineageNode,
        conn: sqlite3.Connection | None = None,
    ) -> LineageNode:
        """Register a lineage node within its tenant domain."""
        c = self._get_connection(conn)
        meta_json = json.dumps(node.metadata or {})

        in_tx = c.in_transaction
        c.execute(
            """
            INSERT INTO lineage_nodes (ledger_id, node_id, node_type, entity_ref, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (ledger_id, node_id) DO UPDATE SET
                node_type = excluded.node_type,
                entity_ref = excluded.entity_ref,
                metadata_json = excluded.metadata_json
            """,
            (node.ledger_id, node.node_id, node.node_type, node.entity_ref, meta_json),
        )
        if not in_tx:
            c.commit()

        cur = c.execute(
            "SELECT created_at FROM lineage_nodes WHERE ledger_id = ? AND node_id = ?",
            (node.ledger_id, node.node_id),
        )
        row = cur.fetchone()
        created_at = row[0] if row else None

        return LineageNode(
            node_id=node.node_id,
            node_type=node.node_type,
            entity_ref=node.entity_ref,
            metadata=node.metadata,
            ledger_id=node.ledger_id,
            created_at=created_at,
        )

    def get_node(
        self,
        ledger_id: str,
        node_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> LineageNode | None:
        """Retrieve a lineage node by ID within its tenant domain."""
        c = self._get_connection(conn)
        cur = c.execute(
            """
            SELECT ledger_id, node_id, node_type, entity_ref, metadata_json, created_at
            FROM lineage_nodes
            WHERE ledger_id = ? AND node_id = ?
            """,
            (ledger_id, node_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return LineageNode(
            ledger_id=row[0],
            node_id=row[1],
            node_type=row[2],
            entity_ref=row[3],
            metadata=json.loads(row[4]),
            created_at=row[5],
        )

    def add_edge(
        self,
        ledger_id: str,
        source_node_id: str,
        target_node_id: str,
        relationship: RelationshipType,
        conn: sqlite3.Connection | None = None,
    ) -> LineageEdge:
        """Add a directed edge with strict insertion-time cycle prevention."""
        edge = LineageEdge(
            ledger_id=ledger_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relationship=relationship,
        )
        c = self._get_connection(conn)

        in_tx = c.in_transaction
        if not in_tx:
            c.execute("BEGIN IMMEDIATE")
        try:
            # 1. Verify existence of both nodes in this ledger
            cur = c.execute(
                "SELECT node_id FROM lineage_nodes WHERE ledger_id = ? AND node_id IN (?, ?)",
                (ledger_id, source_node_id, target_node_id),
            )
            found_nodes = {row[0] for row in cur.fetchall()}
            if source_node_id not in found_nodes:
                raise LineageNodeNotFoundError(
                    f"Source node '{source_node_id}' not found in ledger '{ledger_id}'"
                )
            if target_node_id not in found_nodes:
                raise LineageNodeNotFoundError(
                    f"Target node '{target_node_id}' not found in ledger '{ledger_id}'"
                )

            # 2. Cycle detection: check if target_node can already reach source_node in this ledger
            # If target can reach source, adding source -> target creates a cycle.
            cur = c.execute(
                """
                WITH RECURSIVE reachability(node, depth) AS (
                    SELECT target_node_id, 0
                    FROM lineage_edges
                    WHERE ledger_id = ? AND source_node_id = ?
                    UNION
                    SELECT e.target_node_id, r.depth + 1
                    FROM lineage_edges e
                    JOIN reachability r ON e.source_node_id = r.node
                    WHERE e.ledger_id = ? AND r.depth < 1000
                )
                SELECT 1 FROM reachability WHERE node = ? LIMIT 1
                """,
                (ledger_id, target_node_id, ledger_id, source_node_id),
            )
            if cur.fetchone() is not None:
                raise LineageCycleError(
                    f"Adding edge {source_node_id} -> {target_node_id} would create a cycle in ledger '{ledger_id}'"
                )

            # 3. Insert edge
            c.execute(
                """
                INSERT INTO lineage_edges (ledger_id, source_node_id, target_node_id, relationship)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (ledger_id, source_node_id, target_node_id, relationship) DO NOTHING
                """,
                (ledger_id, source_node_id, target_node_id, relationship),
            )
            if not in_tx:
                c.execute("COMMIT")
        except Exception:
            if not in_tx and c.in_transaction:
                c.execute("ROLLBACK")
            raise

        cur = c.execute(
            """
            SELECT created_at FROM lineage_edges
            WHERE ledger_id = ? AND source_node_id = ? AND target_node_id = ? AND relationship = ?
            """,
            (ledger_id, source_node_id, target_node_id, relationship),
        )
        row = cur.fetchone()
        created_at = row[0] if row else None

        return LineageEdge(
            ledger_id=ledger_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relationship=relationship,
            created_at=created_at,
        )
