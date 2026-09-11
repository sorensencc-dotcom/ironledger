"""Staging & review endpoints for IronLedger Operator Workbench."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ironledger.audit import append_audit_event
from ironledger.conventions import validate_same_currency_balance
from ironledger.ingest.identity import canonical_payee
from ironledger.review import state
from ironledger.review.rules import resolve_rule_row
from ironledger.web.schemas import (
    PostingSchema,
    StagedApproveRequest,
    StagedSplitRequest,
    StagedTransactionResponse,
)

router = APIRouter(prefix="/api/staging", tags=["staging"])


def get_db(request: Request) -> sqlite3.Connection:
    """Dependency to retrieve database connection from app state."""
    return request.app.state.get_db()


class CategorizeRequest(BaseModel):
    target_account: Optional[str] = None
    contra_account: Optional[str] = None
    notes: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None


@router.get("", response_model=List[StagedTransactionResponse])
def list_staged_transactions(
    status: Optional[str] = Query(None, description="Filter by status: pending, categorized, approved, rejected"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
) -> List[StagedTransactionResponse]:
    """List staged transactions with postings, confidence scores, and rule match metadata."""
    query = (
        "SELECT st.staged_transaction_id, st.source_record_id, sr.source_document_id, "
        "       st.proposed_date, st.payee, st.narration, st.status, st.external_id, "
        "       sd.raw_payload_ref, sd.provenance "
        "FROM staged_transactions st "
        "JOIN source_records sr ON sr.source_record_id = st.source_record_id "
        "JOIN source_documents sd ON sd.source_document_id = sr.source_document_id "
    )
    params: list[Any] = []
    if status:
        query += " WHERE st.status = ?"
        params.append(status)
    query += " ORDER BY st.proposed_date DESC, st.staged_transaction_id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(query, params).fetchall()
    results: list[StagedTransactionResponse] = []

    for stx_id, srec_id, sdoc_id, date, payee, narration, st_status, ext_id, raw_ref, prov in rows:
        postings_rows = db.execute(
            "SELECT account, currency, minor_units, minor_unit_scale, role "
            "FROM staged_postings WHERE staged_transaction_id = ? "
            "ORDER BY posting_index ASC",
            (stx_id,),
        ).fetchall()

        postings: list[PostingSchema] = []
        imported_currency = "USD"
        imported_minor_units = 0
        imported_scale = 2
        importing_account = None

        for p_acc, p_curr, p_units, p_scale, p_role in postings_rows:
            if p_role == "imported":
                imported_currency = p_curr
                imported_minor_units = p_units
                imported_scale = p_scale
                importing_account = p_acc
            if p_acc is not None:
                postings.append(
                    PostingSchema(
                        account=p_acc,
                        currency=p_curr,
                        minor_units=p_units,
                        scale=p_scale,
                    )
                )

        # Confidence calculation & rule matching
        confidence_score: float = 0.20
        matched_rule_id: Optional[str] = None

        if st_status == "approved":
            confidence_score = 1.00
        elif st_status == "categorized":
            confidence_score = 0.85
        else:
            # Check rule match
            hit = resolve_rule_row(db, canonical_payee(payee), importing_account)
            if hit is not None:
                matched_rule_id, _ = hit
                confidence_score = 0.95

        results.append(
            StagedTransactionResponse(
                staged_id=stx_id,
                source_document_id=sdoc_id,
                source_record_id=srec_id,
                date=date,
                payee=payee,
                narration=narration,
                currency=imported_currency,
                minor_units=imported_minor_units,
                scale=imported_scale,
                postings=postings,
                status=st_status,
                confidence_score=confidence_score,
                matched_rule_id=matched_rule_id,
                notes=None,
                external_id=ext_id,
                raw_payload_ref=raw_ref,
                provenance=prov,
            )
        )

    return results


@router.post("/{stx_id}/categorize")
def categorize_transaction(
    stx_id: str,
    payload: CategorizeRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    """Assign target contra account to a staged transaction."""
    target_acc = payload.target_account or payload.contra_account
    if not target_acc:
        raise HTTPException(status_code=400, detail="target_account or contra_account is required")
    try:
        state.categorize(db, stx_id, target_acc)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "staged_id": stx_id, "status": "categorized"}


@router.post("/{stx_id}/approve")
def approve_transaction(
    stx_id: str,
    payload: Optional[StagedApproveRequest] = None,
    db: sqlite3.Connection = Depends(get_db),
):
    """Approve a staged transaction for compilation."""
    try:
        if payload and payload.target_account:
            state.categorize(db, stx_id, payload.target_account)
        state.approve(db, stx_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "staged_id": stx_id, "status": "approved"}


@router.post("/{stx_id}/reject")
def reject_transaction(
    stx_id: str,
    payload: Optional[RejectRequest] = None,
    db: sqlite3.Connection = Depends(get_db),
):
    """Reject a staged transaction."""
    try:
        reason = payload.reason if payload else None
        state.reject(db, stx_id, reason=reason)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "staged_id": stx_id, "status": "rejected"}


@router.post("/{stx_id}/split")
def split_transaction(
    stx_id: str,
    payload: StagedSplitRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    """Split the contra leg of a staged transaction into multiple postings."""
    try:
        # Get imported leg
        imported_row = db.execute(
            "SELECT source_record_id, account, minor_units, currency, minor_unit_scale "
            "FROM staged_postings WHERE staged_transaction_id = ? AND role = 'imported'",
            (stx_id,),
        ).fetchone()
        if not imported_row:
            raise HTTPException(status_code=404, detail="Staged transaction not found")

        srec_id, imp_acc, imp_units, imp_curr, imp_scale = imported_row

        # Build complete postings sequence to balance check
        all_postings_dict = [
            {
                "account": imp_acc,
                "currency": imp_curr,
                "minor_units": imp_units,
                "scale": imp_scale,
            }
        ]
        for p in payload.postings:
            all_postings_dict.append(
                {
                    "account": p.account,
                    "currency": p.currency,
                    "minor_units": p.minor_units,
                    "scale": p.scale,
                }
            )

        validate_same_currency_balance(all_postings_dict)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Delete existing contra postings
        db.execute(
            "DELETE FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
            (stx_id,),
        )

        # Insert new contra postings
        for idx, p in enumerate(payload.postings, start=1):
            posting_id = f"spst_{uuid.uuid4().hex[:12]}"
            db.execute(
                "INSERT INTO staged_postings ("
                "   staged_posting_id, staged_transaction_id, source_record_id, role, "
                "   posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc"
                ") VALUES (?, ?, ?, 'contra', ?, ?, ?, ?, ?, ?)",
                (
                    posting_id,
                    stx_id,
                    srec_id,
                    idx,
                    p.account,
                    p.minor_units,
                    p.currency,
                    p.scale,
                    now_utc,
                ),
            )

        # Update status to categorized
        db.execute(
            "UPDATE staged_transactions SET status = 'categorized', categorized_at_utc = ? "
            "WHERE staged_transaction_id = ?",
            (now_utc, stx_id),
        )

        append_audit_event(
            db,
            actor="operator",
            action=f"review split ({len(payload.postings)} legs)",
            target=stx_id,
            result="ok",
            ts_utc=now_utc,
        )

        db.commit()

        # Query all updated postings to return
        updated_rows = db.execute(
            "SELECT account, currency, minor_units, minor_unit_scale FROM staged_postings "
            "WHERE staged_transaction_id = ? ORDER BY posting_index ASC",
            (stx_id,),
        ).fetchall()

        all_postings = [
            PostingSchema(
                account=r[0],
                currency=r[1],
                minor_units=r[2],
                scale=r[3],
            )
            for r in updated_rows
        ]

        return {
            "success": True,
            "staged_id": stx_id,
            "status": "categorized",
            "postings": all_postings,
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

