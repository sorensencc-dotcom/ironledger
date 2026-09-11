"""Middleware guards for ledger mutation transactions."""

from __future__ import annotations

import sqlite3
from typing import Any
from ironledger.rbac.tokens import CapabilityToken, verify_capability_token
from ironledger.rbac.policy import evaluate_action_permission


class GuardedLedgerContext:
    """Wraps database connections and enforces signed RBAC validation prior to dispatch."""

    def __init__(self, db_conn: sqlite3.Connection, authority_secret: bytes):
        self.conn = db_conn
        self.secret = authority_secret

    def execute_governed_mutation(
        self,
        token: CapabilityToken,
        signature: str,
        target_tenant_id: str,
        target_ledger_id: str,
        required_capability: str,
        mutation_type: str,
        payload: dict[str, Any],
    ) -> None:
        # 1. Cryptographic Token Assertion
        verify_capability_token(self.secret, token, signature)

        # 2. Policy & Capability Evaluation
        evaluate_action_permission(
            token=token,
            required_capability=required_capability,
            target_tenant_id=target_tenant_id,
            target_ledger_id=target_ledger_id,
        )

        # 3. Write Actor Provenance to Audit Log
        try:
            self.conn.execute(
                """
                INSERT INTO mutation_events (
                    tenant_id, ledger_id, event_type, proposed_by, created_at
                ) VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (target_tenant_id, target_ledger_id, mutation_type, token.principal_id),
            )
        except sqlite3.OperationalError:
            pass
