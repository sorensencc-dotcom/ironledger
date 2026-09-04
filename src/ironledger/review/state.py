"""Phase 2b review lifecycle transitions: categorize, approve, reject, reopen, auto_match."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ironledger.audit import append_audit_event
from ironledger.conventions import ConventionError, validate_account_name
from ironledger.ingest.identity import canonical_payee
from ironledger.review.approve_gate import check_approvable
from ironledger.review.rules import resolve_rule_row

__all__ = ["ReviewStateError", "categorize", "approve", "reject", "reopen", "auto_match"]


class ReviewStateError(ValueError):
    """An unknown staged transaction id or an illegal review-state transition."""


def _now(now_utc: str | None) -> str:
    return now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _status(conn: sqlite3.Connection, stx_id: str) -> str:
    row = conn.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (stx_id,)
    ).fetchone()
    if row is None:
        raise ReviewStateError(f"unknown staged transaction {stx_id!r}")
    return row[0]


def categorize(
    conn: sqlite3.Connection,
    stx_id: str,
    target_account: str,
    *,
    rule_id: str | None = None,
    now_utc: str | None = None,
) -> None:
    try:
        validate_account_name(target_account)
    except ConventionError as exc:
        raise ReviewStateError(str(exc)) from exc

    status = _status(conn, stx_id)
    if status in ("rejected", "approved"):
        raise ReviewStateError(
            f"{stx_id} is {status}; run 'ironledger review reopen {stx_id}' before categorizing"
        )

    ts = _now(now_utc)
    conn.execute(
        "UPDATE staged_postings SET account = ? WHERE staged_transaction_id = ? AND role = 'contra'",
        (target_account, stx_id),
    )
    if status == "pending":
        conn.execute(
            "UPDATE staged_transactions SET status = 'categorized', categorized_at_utc = ? "
            "WHERE staged_transaction_id = ?",
            (ts, stx_id),
        )

    detail = target_account if rule_id is None else f"{target_account}; rule {rule_id}"
    append_audit_event(
        conn, actor="operator", action=f"review categorize ({detail})",
        target=stx_id, result="ok", ts_utc=now_utc,
    )


def approve(conn: sqlite3.Connection, stx_id: str, *, now_utc: str | None = None) -> None:
    check_approvable(conn, stx_id)  # raises ApproveGateError on failure
    ts = _now(now_utc)
    conn.execute(
        "UPDATE staged_transactions SET status = 'approved', decided_at_utc = ? "
        "WHERE staged_transaction_id = ?",
        (ts, stx_id),
    )
    append_audit_event(
        conn, actor="operator", action="review approve", target=stx_id, result="ok", ts_utc=now_utc,
    )


def reject(
    conn: sqlite3.Connection, stx_id: str, *, reason: str | None = None, now_utc: str | None = None
) -> None:
    status = _status(conn, stx_id)
    if status == "approved":
        raise ReviewStateError(f"{stx_id} is approved; approved is terminal in Phase 2b")
    if status == "rejected":
        return
    ts = _now(now_utc)
    conn.execute(
        "UPDATE staged_transactions SET status = 'rejected', reject_reason = ?, decided_at_utc = ? "
        "WHERE staged_transaction_id = ?",
        (reason, ts, stx_id),
    )
    append_audit_event(
        conn, actor="operator", action="review reject", target=stx_id, result="ok", ts_utc=now_utc,
    )


def reopen(conn: sqlite3.Connection, stx_id: str, *, now_utc: str | None = None) -> None:
    status = _status(conn, stx_id)
    if status not in ("categorized", "rejected"):
        raise ReviewStateError(
            f"{stx_id} is {status}; only a categorized or rejected row can be reopened"
        )
    conn.execute(
        "UPDATE staged_transactions SET status = 'pending', reject_reason = NULL, "
        "categorized_at_utc = NULL, decided_at_utc = NULL WHERE staged_transaction_id = ?",
        (stx_id,),
    )
    append_audit_event(
        conn, actor="operator", action=f"review reopen (from {status})",
        target=stx_id, result="ok", ts_utc=now_utc,
    )


def auto_match(
    conn: sqlite3.Connection,
    *,
    importing_account: str | None = None,
    now_utc: str | None = None,
) -> tuple[int, int]:
    sql = (
        "SELECT st.staged_transaction_id, st.payee, imp.account "
        "FROM staged_transactions st "
        "JOIN staged_postings imp ON imp.staged_transaction_id = st.staged_transaction_id "
        "  AND imp.role = 'imported' "
        "JOIN staged_postings con ON con.staged_transaction_id = st.staged_transaction_id "
        "  AND con.role = 'contra' "
        "WHERE st.status = 'pending' AND con.account IS NULL"
    )
    params: tuple = ()
    if importing_account is not None:
        sql += " AND imp.account = ?"
        params = (importing_account,)
    candidates = conn.execute(sql, params).fetchall()

    matched = 0
    ts = _now(now_utc)
    for stx_id, payee, imp_account in candidates:
        hit = resolve_rule_row(conn, canonical_payee(payee), imp_account, now_utc=now_utc)
        if hit is None:
            continue
        rule_id, target_account = hit
        conn.execute(
            "UPDATE staged_postings SET account = ? "
            "WHERE staged_transaction_id = ? AND role = 'contra'",
            (target_account, stx_id),
        )
        conn.execute(
            "UPDATE staged_transactions SET status = 'categorized', categorized_at_utc = ? "
            "WHERE staged_transaction_id = ?",
            (ts, stx_id),
        )
        append_audit_event(
            conn, actor="operator",
            action=f"review auto-match ({target_account}; rule {rule_id})",
            target=stx_id, result="ok", ts_utc=now_utc,
        )
        matched += 1

    append_audit_event(
        conn, actor="operator",
        action=f"review auto-match (matched {matched} of {len(candidates)})",
        target=importing_account or "all", result="ok", ts_utc=now_utc,
    )
    return matched, len(candidates)
