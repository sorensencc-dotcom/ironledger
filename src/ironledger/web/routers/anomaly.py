"""Anomaly and fraud-flag endpoints backed by the pure rational detector engine."""

from __future__ import annotations

import sqlite3
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ironledger.governance.anomaly import (
    AnomalyEngineError,
    NormalizedTransaction,
    VALID_RULE_TYPES,
    resolve_anomaly_flag,
    scan_and_persist_anomalies,
)
from ironledger.web.auth import require_operator
from ironledger.web.schemas import (
    AnomalyFlagsListResponse,
    AnomalyResolveRequest,
    AnomalyResolveResponse,
    AnomalyScanRequest,
    AnomalyScanResponse,
)

router = APIRouter(prefix="/api/anomaly", tags=["anomaly"])


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = request.app.state.get_db()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/flags", response_model=AnomalyFlagsListResponse)
def list_flags(
    ledger_id: str = "default",
    status: Optional[str] = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """List anomaly flags for a ledger, optionally filtered by resolution status."""
    query = """
        SELECT flag_id, staged_transaction_id, rule_type, severity,
               score_numerator, score_denominator, resolution_status, created_at_utc
        FROM anomaly_flags
        WHERE ledger_id = ?
    """
    params: list[object] = [ledger_id]
    if status == "OPEN":
        query += " AND resolution_status IS NULL"
    elif status == "RESOLVED":
        query += " AND resolution_status IS NOT NULL"
    elif status:
        query += " AND resolution_status = ?"
        params.append(status)
    query += " ORDER BY created_at_utc DESC"

    rows = conn.execute(query, tuple(params)).fetchall()
    flags = [
        {
            "flag_id": r[0],
            "staged_transaction_id": r[1],
            "rule_type": r[2],
            "severity": r[3],
            "score_numerator": r[4],
            "score_denominator": r[5],
            "resolution_status": r[6],
            "created_at_utc": r[7],
        }
        for r in rows
    ]
    return {"ledger_id": ledger_id, "flags": flags, "count": len(flags)}


@router.post("/scan", response_model=AnomalyScanResponse)
def scan(
    payload: AnomalyScanRequest,
    conn: sqlite3.Connection = Depends(get_db),
    _auth: None = Depends(require_operator),
) -> dict:
    """Scan staged transactions for anomalies and persist detected flags."""
    rules = tuple(payload.rules) if payload.rules else VALID_RULE_TYPES
    rows = conn.execute(
        """
        SELECT t.staged_transaction_id, p.minor_units, p.currency, coalesce(p.account, ''), t.payee, t.narration, t.created_at_utc
        FROM staged_transactions t
        JOIN staged_postings p ON t.staged_transaction_id = p.staged_transaction_id AND p.role = 'imported'
        ORDER BY t.created_at_utc ASC
        """
    ).fetchall()
    transactions = [
        NormalizedTransaction(
            id=r[0],
            ledger_id=payload.ledger_id,
            amount_cents=r[1],
            currency=r[2],
            account_id=r[3],
            payee=r[4] or "",
            description=r[5] or "",
            timestamp_utc=r[6],
        )
        for r in rows
    ]
    try:
        findings = scan_and_persist_anomalies(conn, payload.ledger_id, transactions, rules=rules)
        conn.commit()
    except AnomalyEngineError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ledger_id": payload.ledger_id,
        "scanned_count": len(transactions),
        "findings": [
            {
                "flag_id": f.flag_id,
                "ledger_id": f.ledger_id,
                "staged_transaction_id": f.staged_transaction_id,
                "rule_type": f.rule_type,
                "severity": f.severity,
                "score_numerator": f.score_numerator,
                "score_denominator": f.score_denominator,
                "details": f.details,
                "created_at_utc": f.created_at_utc,
            }
            for f in findings
        ],
    }


@router.post("/flags/{flag_id}/resolve", response_model=AnomalyResolveResponse)
def resolve(
    flag_id: str,
    payload: AnomalyResolveRequest,
    ledger_id: str = "default",
    conn: sqlite3.Connection = Depends(get_db),
    _auth: None = Depends(require_operator),
) -> dict:
    """Atomically resolve an anomaly flag and append a governance audit event."""
    try:
        success = resolve_anomaly_flag(
            conn=conn,
            ledger_id=ledger_id,
            flag_id=flag_id,
            resolution_status=payload.resolution_status,
            actor=payload.actor,
            reason=payload.reason,
        )
    except AnomalyEngineError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    if not success:
        conn.rollback()
        raise HTTPException(status_code=422, detail=f"Anomaly flag {flag_id} is already resolved")
    conn.commit()
    return {"success": True, "flag_id": flag_id, "resolution_status": payload.resolution_status}
