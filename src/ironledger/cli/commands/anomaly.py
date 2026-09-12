"""CLI subcommands for pure rational anomaly and fraud detection."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ironledger.db.connection import connect
from ironledger.governance.anomaly import (
    AnomalyEngineError,
    NormalizedTransaction,
    VALID_RESOLUTIONS,
    resolve_anomaly_flag,
    scan_and_persist_anomalies,
)
from ironledger.governance.migrations import migrate_governed


def run_anomaly_scan(
    db_path: str | Path,
    ledger_id: str,
) -> int:
    """Scan staged transactions for anomalies using pure rational algorithms."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        # Load staged transactions for this ledger
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.staged_transaction_id, p.minor_units, p.currency, coalesce(p.account, ''), t.payee, t.narration, t.created_at_utc
            FROM staged_transactions t
            JOIN staged_postings p ON t.staged_transaction_id = p.staged_transaction_id AND p.role = 'imported'
            ORDER BY t.created_at_utc ASC
            """
        )
        rows = cursor.fetchall()
        txs = [
            NormalizedTransaction(
                id=r[0],
                ledger_id=ledger_id,
                amount_cents=r[1],
                currency=r[2],
                account_id=r[3],
                payee=r[4] or "",
                description=r[5] or "",
                timestamp_utc=r[6],
            )
            for r in rows
        ]

        findings = scan_and_persist_anomalies(conn, ledger_id, txs)
        conn.commit()
        print(f"Scanned {len(txs)} transactions in ledger {ledger_id}.")
        print(f"Detected and persisted {len(findings)} anomaly flags.")
        for f in findings:
            print(f"  - [{f.severity}] {f.rule_type}: tx={f.staged_transaction_id} flag={f.flag_id}")
        return 0
    except (AnomalyEngineError, Exception) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def run_anomaly_list(
    db_path: str | Path,
    ledger_id: str,
    status: str | None = None,
) -> int:
    """List anomaly flags for a given ledger."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        cursor = conn.cursor()
        query = """
            SELECT flag_id, staged_transaction_id, rule_type, severity,
                   score_numerator, score_denominator, resolution_status, created_at_utc
            FROM anomaly_flags
            WHERE ledger_id = ?
        """
        params: list[str] = [ledger_id]
        if status == "OPEN":
            query += " AND resolution_status IS NULL"
        elif status == "RESOLVED":
            query += " AND resolution_status IS NOT NULL"
        elif status:
            query += " AND resolution_status = ?"
            params.append(status)

        query += " ORDER BY created_at_utc DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        print(f"Found {len(rows)} anomaly flags for ledger {ledger_id}:")
        for r in rows:
            res_str = r[6] if r[6] else "OPEN"
            print(f"  - {r[0]}: [{r[3]}] {r[2]} (tx={r[1]}, score={r[4]}/{r[5]}, status={res_str})")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def run_anomaly_resolve(
    db_path: str | Path,
    ledger_id: str,
    flag_id: str,
    status: str,
    actor: str = "operator",
    reason: str = "",
) -> int:
    """Atomically resolve an anomaly flag."""
    resolved_db = Path(db_path).resolve()
    conn = connect(resolved_db)
    try:
        migrate_governed(conn, resolved_db)
        success = resolve_anomaly_flag(
            conn=conn,
            ledger_id=ledger_id,
            flag_id=flag_id,
            resolution_status=status,
            actor=actor,
            reason=reason,
        )
        if success:
            conn.commit()
            print(f"Resolved flag {flag_id} as {status} (actor={actor})")
            return 0
        else:
            print(f"Failed to resolve flag {flag_id} (already resolved or not found)", file=sys.stderr)
            return 1
    except (AnomalyEngineError, Exception) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
