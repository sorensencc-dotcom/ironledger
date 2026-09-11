"""Dual projection hashing and in-memory mutation state dispatcher."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ironledger.manifests import GENESIS_MANIFEST_HASH

GENESIS_PROJECTION_HASH = "1e3b03f64f2e93ca3cde5c5fd5e63b6194416b8b31871df1153ab643f7342314"

STATIC_PROJECTION_COLUMNS: dict[str, list[str]] = {
    "staged_transactions": [
        "ledger_id", "staged_transaction_id", "source_record_id",
        "status", "proposed_date", "payee", "narration", "reject_reason"
    ],
    "staged_postings": [
        "ledger_id", "staged_posting_id", "staged_transaction_id", "source_record_id",
        "role", "posting_index", "account", "minor_units", "currency", "minor_unit_scale"
    ],
    "categorization_rules": [
        "ledger_id", "rule_id", "match_type", "pattern", "importing_account", "target_account", "priority", "active"
    ],
    "price_history": [
        "ledger_id", "id", "directive_date", "base_currency", "quote_currency",
        "rate_numerator", "rate_denominator", "precision_scale", "source"
    ],
    "compile_runs": [
        "ledger_id", "compile_run_id", "beancount_version", "compiler_version",
        "input_hash", "intended_output_hash", "actual_output_hash", "status"
    ],
}

TABLE_ORDER_CLAUSES: dict[str, str] = {
    "staged_transactions": "ledger_id ASC, staged_transaction_id ASC",
    "staged_postings": "ledger_id ASC, staged_transaction_id ASC, posting_index ASC, staged_posting_id ASC",
    "categorization_rules": "ledger_id ASC, rule_id ASC",
    "price_history": "ledger_id ASC, base_currency ASC, quote_currency ASC, directive_date ASC, id ASC",
    "compile_runs": "ledger_id ASC, compile_run_id ASC",
}


def compute_projection_hash(conn: sqlite3.Connection, ledger_id: str) -> str:
    """Compute canonical SHA-256 hash over tenant projection state ordered by primary keys."""
    payload = []
    for table, cols in STATIC_PROJECTION_COLUMNS.items():
        col_str = ", ".join(cols)
        order_clause = TABLE_ORDER_CLAUSES[table]
        cur = conn.execute(
            f"SELECT {col_str} FROM {table} WHERE ledger_id = ? ORDER BY {order_clause}",
            (ledger_id,),
        )
        rows = []
        for row in cur.fetchall():
            normalized_row = []
            for val in row:
                if val is None:
                    normalized_row.append(None)
                elif type(val) is int and not isinstance(val, bool):
                    normalized_row.append(val)
                elif isinstance(val, bool):
                    raise TypeError("Boolean value encountered in projection table; must be integer 0 or 1")
                else:
                    normalized_row.append(str(val))
            rows.append(normalized_row)
        payload.append([table, cols, rows])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dispatch_event_mutation(
    conn: sqlite3.Connection,
    ledger_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Apply in-memory SQL state transitions for an event mutation."""
    if event_type == "STAGE_TRANSACTION":
        sr = payload["source_record"]
        # Source document
        conn.execute(
            """
            INSERT OR IGNORE INTO source_documents (
                source_document_id, ledger_id, mime_type, encoding, provenance,
                acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sr["source_document_id"], ledger_id, sr["mime_type"], sr["encoding"],
                sr["provenance"], payload["created_at_utc"], sr["content_sha256"],
                sr["raw_payload_ref"], payload["created_at_utc"]
            ),
        )
        # Source record
        conn.execute(
            """
            INSERT OR IGNORE INTO source_records (
                source_record_id, ledger_id, source_document_id, record_index,
                canonical_payload, content_sha256, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["source_record_id"], ledger_id, sr["source_document_id"],
                sr["record_index"], sr["canonical_payload"], sr["content_sha256"],
                payload["created_at_utc"]
            ),
        )
        # Staged transaction
        conn.execute(
            """
            INSERT OR REPLACE INTO staged_transactions (
                staged_transaction_id, ledger_id, source_record_id, status, proposed_date,
                payee, narration, identity_algo_version, identity_method, identity_fingerprint,
                created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["staged_transaction_id"], ledger_id, payload["source_record_id"],
                payload["status"], payload["proposed_date"], payload.get("payee", ""),
                payload.get("narration", ""), payload["identity_algo_version"],
                payload["identity_method"], payload["identity_fingerprint"],
                payload["created_at_utc"]
            ),
        )
        # Postings
        for p in payload["postings"]:
            conn.execute(
                """
                INSERT OR REPLACE INTO staged_postings (
                    staged_posting_id, ledger_id, staged_transaction_id, source_record_id,
                    role, posting_index, account, minor_units, currency, minor_unit_scale,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p["staged_posting_id"], ledger_id, payload["staged_transaction_id"],
                    p["source_record_id"], p["role"], p["posting_index"],
                    p.get("account"), p["minor_units"], p["currency"],
                    p["minor_unit_scale"], p.get("created_at_utc", payload["created_at_utc"])
                ),
            )

    elif event_type == "REVIEW_DECISION":
        staged_tx_id = payload["staged_transaction_id"]
        new_status = payload["new_status"]
        decided_at = payload["decided_at_utc"]
        reject_reason = payload.get("reject_reason")
        assigned_account = payload.get("assigned_account")

        conn.execute(
            """
            UPDATE staged_transactions
            SET status = ?, decided_at_utc = ?, reject_reason = ?
            WHERE ledger_id = ? AND staged_transaction_id = ?
            """,
            (new_status, decided_at, reject_reason, ledger_id, staged_tx_id),
        )
        if assigned_account:
            conn.execute(
                """
                UPDATE staged_postings
                SET account = ?
                WHERE ledger_id = ? AND staged_transaction_id = ? AND role = 'contra'
                """,
                (assigned_account, ledger_id, staged_tx_id),
            )

    elif event_type == "COMPILE_LEDGER":
        status_val = payload["status"].lower()
        if status_val == "success":
            status_val = "succeeded"
        started_at = payload.get("started_at_utc", "2026-09-01T12:00:00Z")
        finished_at = payload.get("finished_at_utc", started_at)
        conn.execute(
            """
            INSERT OR REPLACE INTO compile_runs (
                compile_run_id, ledger_id, beancount_version, compiler_version,
                input_hash, intended_output_hash, actual_output_hash, status,
                started_at_utc, finished_at_utc, recovery_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["compile_run_id"], ledger_id, payload["beancount_version"],
                payload["compiler_version"], payload["input_hash"],
                payload["intended_output_hash"], payload["actual_output_hash"],
                status_val, started_at, finished_at, payload.get("recovery_state", "none")
            ),
        )

    elif event_type == "PRICE_DIRECTIVE":
        conn.execute(
            """
            INSERT INTO price_history (
                id, ledger_id, directive_date, base_currency, quote_currency,
                rate_numerator, rate_denominator, precision_scale, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ledger_id, directive_date, base_currency, quote_currency) DO UPDATE SET
                rate_numerator = excluded.rate_numerator,
                rate_denominator = excluded.rate_denominator,
                precision_scale = excluded.precision_scale,
                source = excluded.source
            """,
            (
                payload["id"], ledger_id, payload["directive_date"],
                payload["base_currency"], payload["quote_currency"],
                payload["rate_numerator"], payload["rate_denominator"],
                payload.get("precision_scale", 4), payload["source"]
            ),
        )

    elif event_type == "RULE_UPDATE":
        action = payload["action"]
        rule_id = payload["rule_id"]
        if action == "CREATE":
            conn.execute(
                """
                INSERT OR REPLACE INTO categorization_rules (
                    rule_id, ledger_id, match_type, pattern, importing_account,
                    target_account, priority, active, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                """,
                (
                    rule_id, ledger_id, payload["match_type"], payload["pattern"],
                    payload.get("importing_account"), payload["target_account"],
                    payload.get("priority", 100), payload.get("active", 1)
                ),
            )
        elif action == "UPDATE":
            conn.execute(
                """
                UPDATE categorization_rules
                SET match_type = ?, pattern = ?, importing_account = ?,
                    target_account = ?, priority = ?, active = ?
                WHERE ledger_id = ? AND rule_id = ?
                """,
                (
                    payload["match_type"], payload["pattern"], payload.get("importing_account"),
                    payload["target_account"], payload.get("priority", 100),
                    payload.get("active", 1), ledger_id, rule_id
                ),
            )
        elif action == "DELETE":
            conn.execute(
                """
                DELETE FROM categorization_rules
                WHERE ledger_id = ? AND rule_id = ?
                """,
                (ledger_id, rule_id),
            )
