"""Tenant-isolated staging queues for asynchronous operations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ironledger.ledger.models import LEDGER_ID_PATTERN
from ironledger.ledger.topology import LedgerRegistry


class StagingManager:
    """Tenant staging queue manager ensuring strict isolation between ledgers."""

    def __init__(self, registry: LedgerRegistry) -> None:
        self.registry = registry

    def _validate_ledger_id(self, ledger_id: str) -> None:
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")

    def enqueue(self, ledger_id: str, operation: dict[str, Any]) -> int:
        """Enqueue a new staging operation for a specific tenant ledger."""
        self._validate_ledger_id(ledger_id)
        if not isinstance(operation, dict):
            raise TypeError("operation must be a dictionary")

        op_json = json.dumps(operation)
        in_tx = self.registry.conn.in_transaction
        if not in_tx:
            self.registry.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self.registry.conn.execute(
                """
                INSERT INTO tenant_staging_operations (ledger_id, operation_json, status)
                VALUES (?, ?, 'pending')
                """,
                (ledger_id, op_json),
            )
            op_id = cur.lastrowid
            if not in_tx:
                self.registry.conn.execute("COMMIT")
            return int(op_id)
        except Exception:
            if not in_tx and self.registry.conn.in_transaction:
                self.registry.conn.execute("ROLLBACK")
            raise

    def peek(self, ledger_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Inspect pending operations for a specific tenant without consuming them."""
        self._validate_ledger_id(ledger_id)
        cur = self.registry.conn.execute(
            """
            SELECT op_id, ledger_id, operation_json, status, created_at
            FROM tenant_staging_operations
            WHERE ledger_id = ? AND status = 'pending'
            ORDER BY op_id ASC
            LIMIT ?
            """,
            (ledger_id, limit),
        )
        rows = cur.fetchall()
        return [
            {
                "op_id": r[0],
                "ledger_id": r[1],
                "operation": json.loads(r[2]),
                "status": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def dequeue(self, ledger_id: str) -> dict[str, Any] | None:
        """Atomically consume and mark the oldest pending operation as processed."""
        self._validate_ledger_id(ledger_id)
        in_tx = self.registry.conn.in_transaction
        if not in_tx:
            self.registry.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self.registry.conn.execute(
                """
                SELECT op_id, operation_json, created_at
                FROM tenant_staging_operations
                WHERE ledger_id = ? AND status = 'pending'
                ORDER BY op_id ASC
                LIMIT 1
                """,
                (ledger_id,),
            )
            row = cur.fetchone()
            if row is None:
                if not in_tx:
                    self.registry.conn.execute("COMMIT")
                return None

            op_id = row[0]
            op_data = json.loads(row[1])
            created_at = row[2]

            self.registry.conn.execute(
                """
                UPDATE tenant_staging_operations
                SET status = 'processed'
                WHERE op_id = ?
                """,
                (op_id,),
            )
            if not in_tx:
                self.registry.conn.execute("COMMIT")

            return {
                "op_id": op_id,
                "ledger_id": ledger_id,
                "operation": op_data,
                "status": "processed",
                "created_at": created_at,
            }
        except Exception:
            if not in_tx and self.registry.conn.in_transaction:
                self.registry.conn.execute("ROLLBACK")
            raise
