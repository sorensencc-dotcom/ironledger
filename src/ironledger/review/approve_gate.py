"""Phase 2b approve-gate: a staged transaction is approvable only when fully categorized,
single-currency, and balanced."""

from __future__ import annotations

import sqlite3

from ironledger.conventions import ConventionError, validate_account_name, validate_same_currency_balance

__all__ = ["ApproveGateError", "check_approvable"]


class ApproveGateError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def check_approvable(conn: sqlite3.Connection, stx_id: str) -> None:
    row = conn.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (stx_id,)
    ).fetchone()
    if row is None:
        raise ApproveGateError("status", f"unknown staged transaction {stx_id!r}")
    if row[0] not in ("pending", "categorized"):
        raise ApproveGateError("status", f"{stx_id} is {row[0]}, not approvable")

    postings = conn.execute(
        "SELECT account, minor_units, currency, minor_unit_scale FROM staged_postings "
        "WHERE staged_transaction_id = ? ORDER BY posting_index",
        (stx_id,),
    ).fetchall()
    if len(postings) < 2:
        raise ApproveGateError("missing_account", f"{stx_id} has fewer than two postings")

    # Explicit NULL / grammar check first, so the caller gets a precise reason
    # slug instead of the generic ConventionError from validate_same_currency_balance.
    for account, _minor, _currency, _scale in postings:
        if account is None:
            raise ApproveGateError("missing_account", f"{stx_id} has a posting with no account")
        try:
            validate_account_name(account)
        except ConventionError as exc:
            raise ApproveGateError("invalid_account", f"{stx_id}: {exc}") from exc

    # Reject any multi-currency transaction outright. validate_same_currency_balance
    # only checks that each currency independently nets to zero, which would let a
    # balanced two-currency transaction through; Phase 2b compiles neither.
    if len({p[2] for p in postings}) > 1:
        raise ApproveGateError(
            "multi_currency", f"{stx_id} mixes currencies {sorted({p[2] for p in postings})}"
        )

    # Reuse the locked convention for the zero-sum / non-zero-amount check.
    try:
        validate_same_currency_balance([
            {"account": a, "minor_units": m, "currency": c, "scale": s}
            for a, m, c, s in postings
        ])
    except ConventionError as exc:
        raise ApproveGateError("unbalanced", f"{stx_id}: {exc}") from exc
