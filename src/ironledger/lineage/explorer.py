"""Bi-directional recursive provenance traversal explorer."""

from __future__ import annotations

import json
import sqlite3

from ironledger.lineage.models import (
    LEDGER_ID_PATTERN,
    NODE_ID_PATTERN,
    LineageEdge,
    LineageGraph,
    LineageNode,
    LineageNodeNotFoundError,
)


class LineageExplorer:
    """Explores upstream provenance and downstream blast-radius in the lineage DAG."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._conn = conn

    def _get_connection(self, conn: sqlite3.Connection | None) -> sqlite3.Connection:
        active_conn = conn if conn is not None else self._conn
        if active_conn is None:
            raise ValueError("No database connection provided")
        return active_conn

    def trace_upstream(
        self,
        ledger_id: str,
        start_node_id: str,
        max_depth: int = 50,
        conn: sqlite3.Connection | None = None,
    ) -> LineageGraph:
        """Trace all upstream ancestor nodes and edges leading to start_node_id."""
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")
        if not isinstance(start_node_id, str) or not NODE_ID_PATTERN.match(start_node_id):
            raise ValueError(f"Invalid start_node_id: {start_node_id!r}")
        if type(max_depth) is not int or isinstance(max_depth, bool) or max_depth < 0:
            raise TypeError("max_depth must be a non-negative integer")

        c = self._get_connection(conn)

        # 1. Fetch all upstream node IDs with recursive CTE
        cur = c.execute(
            """
            WITH RECURSIVE upstream(node_id, depth) AS (
                SELECT ?, 0
                UNION
                SELECT e.source_node_id, u.depth + 1
                FROM lineage_edges e
                JOIN upstream u ON e.target_node_id = u.node_id
                WHERE e.ledger_id = ? AND u.depth < ?
            )
            SELECT DISTINCT n.ledger_id, n.node_id, n.node_type, n.entity_ref, n.metadata_json, n.created_at
            FROM upstream u
            JOIN lineage_nodes n ON n.ledger_id = ? AND n.node_id = u.node_id
            ORDER BY u.depth ASC
            """,
            (start_node_id, ledger_id, max_depth, ledger_id),
        )
        node_rows = cur.fetchall()
        if not node_rows:
            # Check if start node exists
            check = c.execute(
                "SELECT 1 FROM lineage_nodes WHERE ledger_id = ? AND node_id = ?",
                (ledger_id, start_node_id),
            ).fetchone()
            if not check:
                raise LineageNodeNotFoundError(f"Node '{start_node_id}' not found in ledger '{ledger_id}'")

        nodes = [
            LineageNode(
                ledger_id=r[0],
                node_id=r[1],
                node_type=r[2],
                entity_ref=r[3],
                metadata=json.loads(r[4]),
                created_at=r[5],
            )
            for r in node_rows
        ]
        node_id_set = {n.node_id for n in nodes}

        # 2. Fetch all connecting edges among the discovered nodes
        placeholders = ",".join("?" for _ in node_id_set)
        edges = []
        if node_id_set:
            edge_params = [ledger_id] + list(node_id_set) + list(node_id_set)
            cur = c.execute(
                f"""
                SELECT ledger_id, source_node_id, target_node_id, relationship, created_at
                FROM lineage_edges
                WHERE ledger_id = ?
                  AND source_node_id IN ({placeholders})
                  AND target_node_id IN ({placeholders})
                """,
                edge_params,
            )
            edges = [
                LineageEdge(
                    ledger_id=r[0],
                    source_node_id=r[1],
                    target_node_id=r[2],
                    relationship=r[3],
                    created_at=r[4],
                )
                for r in cur.fetchall()
            ]

        return LineageGraph(nodes=nodes, edges=edges)

    def trace_downstream(
        self,
        ledger_id: str,
        start_node_id: str,
        max_depth: int = 50,
        conn: sqlite3.Connection | None = None,
    ) -> LineageGraph:
        """Trace all downstream descendant nodes and edges originating from start_node_id."""
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")
        if not isinstance(start_node_id, str) or not NODE_ID_PATTERN.match(start_node_id):
            raise ValueError(f"Invalid start_node_id: {start_node_id!r}")
        if type(max_depth) is not int or isinstance(max_depth, bool) or max_depth < 0:
            raise TypeError("max_depth must be a non-negative integer")

        c = self._get_connection(conn)

        cur = c.execute(
            """
            WITH RECURSIVE downstream(node_id, depth) AS (
                SELECT ?, 0
                UNION
                SELECT e.target_node_id, d.depth + 1
                FROM lineage_edges e
                JOIN downstream d ON e.source_node_id = d.node_id
                WHERE e.ledger_id = ? AND d.depth < ?
            )
            SELECT DISTINCT n.ledger_id, n.node_id, n.node_type, n.entity_ref, n.metadata_json, n.created_at
            FROM downstream d
            JOIN lineage_nodes n ON n.ledger_id = ? AND n.node_id = d.node_id
            ORDER BY d.depth ASC
            """,
            (start_node_id, ledger_id, max_depth, ledger_id),
        )
        node_rows = cur.fetchall()
        if not node_rows:
            check = c.execute(
                "SELECT 1 FROM lineage_nodes WHERE ledger_id = ? AND node_id = ?",
                (ledger_id, start_node_id),
            ).fetchone()
            if not check:
                raise LineageNodeNotFoundError(f"Node '{start_node_id}' not found in ledger '{ledger_id}'")

        nodes = [
            LineageNode(
                ledger_id=r[0],
                node_id=r[1],
                node_type=r[2],
                entity_ref=r[3],
                metadata=json.loads(r[4]),
                created_at=r[5],
            )
            for r in node_rows
        ]
        node_id_set = {n.node_id for n in nodes}

        placeholders = ",".join("?" for _ in node_id_set)
        edges = []
        if node_id_set:
            edge_params = [ledger_id] + list(node_id_set) + list(node_id_set)
            cur = c.execute(
                f"""
                SELECT ledger_id, source_node_id, target_node_id, relationship, created_at
                FROM lineage_edges
                WHERE ledger_id = ?
                  AND source_node_id IN ({placeholders})
                  AND target_node_id IN ({placeholders})
                """,
                edge_params,
            )
            edges = [
                LineageEdge(
                    ledger_id=r[0],
                    source_node_id=r[1],
                    target_node_id=r[2],
                    relationship=r[3],
                    created_at=r[4],
                )
                for r in cur.fetchall()
            ]

        return LineageGraph(nodes=nodes, edges=edges)

    def get_root_ancestors(
        self,
        ledger_id: str,
        start_node_id: str,
        max_depth: int = 50,
        conn: sqlite3.Connection | None = None,
    ) -> list[LineageNode]:
        """Find all upstream root nodes (nodes with no incoming edges in the lineage subgraph)."""
        graph = self.trace_upstream(ledger_id, start_node_id, max_depth=max_depth, conn=conn)
        target_ids = {e.target_node_id for e in graph.edges}
        return [n for n in graph.nodes if n.node_id not in target_ids]

    def get_leaf_descendants(
        self,
        ledger_id: str,
        start_node_id: str,
        max_depth: int = 50,
        conn: sqlite3.Connection | None = None,
    ) -> list[LineageNode]:
        """Find all downstream leaf nodes (nodes with no outgoing edges in the lineage subgraph)."""
        graph = self.trace_downstream(ledger_id, start_node_id, max_depth=max_depth, conn=conn)
        source_ids = {e.source_node_id for e in graph.edges}
        return [n for n in graph.nodes if n.node_id not in source_ids]
