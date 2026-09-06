from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from ironledger.conventions import validate_utc_timestamp


def _now(now_utc: str | None) -> str:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(now_utc)
    return now_utc


def next_journal_seq(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT seq FROM compile_journal ORDER BY seq DESC LIMIT 1")
    row = cursor.fetchone()
    return 1 if row is None else int(row[0]) + 1


def append_compile_journal(
    conn: sqlite3.Connection,
    compile_run_id: str,
    state: str,
    detail: str = "",
    now_utc: str | None = None,
) -> int:
    ts = _now(now_utc)
    seq = next_journal_seq(conn)
    conn.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (seq, compile_run_id, state, ts, detail),
    )
    conn.commit()
    return seq


def start_compile_run(
    conn: sqlite3.Connection,
    compile_run_id: str,
    beancount_version: str,
    compiler_version: str,
    input_hash: str,
    intended_output_hash: str,
    now_utc: str | None = None,
) -> None:
    ts = _now(now_utc)
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, status, started_at_utc, recovery_state) "
        "VALUES (?, ?, ?, ?, ?, 'started', ?, 'none')",
        (compile_run_id, beancount_version, compiler_version, input_hash, intended_output_hash, ts),
    )
    conn.commit()
    append_compile_journal(conn, compile_run_id, "started", now_utc=ts)


def finish_compile_run(
    conn: sqlite3.Connection,
    compile_run_id: str,
    actual_output_hash: str,
    now_utc: str | None = None,
) -> None:
    ts = _now(now_utc)
    conn.execute(
        "UPDATE compile_runs SET status = 'succeeded', actual_output_hash = ?, finished_at_utc = ? "
        "WHERE compile_run_id = ?",
        (actual_output_hash, ts, compile_run_id),
    )
    conn.commit()
    append_compile_journal(conn, compile_run_id, "succeeded", now_utc=ts)


def fail_compile_run(
    conn: sqlite3.Connection,
    compile_run_id: str,
    detail: str = "",
    now_utc: str | None = None,
) -> None:
    ts = _now(now_utc)
    conn.execute(
        "UPDATE compile_runs SET status = 'failed', finished_at_utc = ? "
        "WHERE compile_run_id = ?",
        (ts, compile_run_id),
    )
    conn.commit()
    append_compile_journal(conn, compile_run_id, "failed", detail=detail, now_utc=ts)


def get_active_started_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT compile_run_id, beancount_version, compiler_version, input_hash, "
        "       intended_output_hash, status, started_at_utc, recovery_state "
        "FROM compile_runs WHERE status = 'started' ORDER BY started_at_utc DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "compile_run_id": row[0],
        "beancount_version": row[1],
        "compiler_version": row[2],
        "input_hash": row[3],
        "intended_output_hash": row[4],
        "status": row[5],
        "started_at_utc": row[6],
        "recovery_state": row[7],
    }


def get_latest_successful_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT compile_run_id, beancount_version, compiler_version, input_hash, "
        "       intended_output_hash, actual_output_hash, status, started_at_utc, finished_at_utc "
        "FROM compile_runs WHERE status IN ('succeeded', 'recovered') "
        "ORDER BY started_at_utc DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "compile_run_id": row[0],
        "beancount_version": row[1],
        "compiler_version": row[2],
        "input_hash": row[3],
        "intended_output_hash": row[4],
        "actual_output_hash": row[5],
        "status": row[6],
        "started_at_utc": row[7],
        "finished_at_utc": row[8],
    }
