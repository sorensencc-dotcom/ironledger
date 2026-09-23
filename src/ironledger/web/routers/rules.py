"""Rule management and Hit Confidence Trend (HCT) drift detection router."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ironledger.conventions import validate_account_name
from ironledger.ingest.identity import canonical_payee
from ironledger.review import state
from ironledger.review.rules import add_rule, disable_rule, list_rules
from ironledger.web.schemas import (
    RuleCandidateRequest,
    RuleCandidateResponse,
    RuleDriftResponse,
)

router = APIRouter(prefix="/api/rules", tags=["rules"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


class CreateRulePayload(BaseModel):
    match_type: str = "exact"
    pattern: str
    target_account: Optional[str] = None
    account: Optional[str] = None
    importing_account: Optional[str] = None
    priority: int = 100
    active: bool = True


@router.get("", response_model=List[dict])
def get_rules(db: sqlite3.Connection = Depends(get_db)):
    """List all categorization rules ordered by priority."""
    return list_rules(db)


@router.post("")
def create_rule(
    payload: CreateRulePayload,
    db: sqlite3.Connection = Depends(get_db),
):
    """Create a new categorization rule."""
    target_acc = payload.target_account or payload.account
    if not target_acc:
        raise HTTPException(status_code=400, detail="target_account or account is required")
    try:
        rule_id = add_rule(
            db,
            match_type=payload.match_type,
            pattern=payload.pattern,
            target_account=target_acc,
            importing_account=payload.importing_account,
            priority=payload.priority,
        )
        matched, total = state.auto_match(db)
        db.commit()
        return {
            "success": True,
            "rule_id": rule_id,
            "matched": matched,
            "candidates": total,
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{rule_id}/disable")
def disable_rule_endpoint(
    rule_id: str,
    db: sqlite3.Connection = Depends(get_db),
):
    """Disable an active rule."""
    try:
        disable_rule(db, rule_id)
        db.commit()
        return {"success": True, "rule_id": rule_id}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidate", response_model=RuleCandidateResponse)
def generate_candidate(
    payload: RuleCandidateRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    """Generate a rule candidate from a staged transaction with retroactive match estimation."""
    row = db.execute(
        "SELECT st.payee, st.narration, sp.account "
        "FROM staged_transactions st "
        "LEFT JOIN staged_postings sp ON sp.staged_transaction_id = st.staged_transaction_id AND sp.role = 'contra' "
        "WHERE st.staged_transaction_id = ?",
        (payload.staged_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Staged transaction not found")

    payee, narration, contra_account = row
    canon_p = canonical_payee(payee)

    if payload.pattern_type == "prefix":
        # First 2 words as prefix
        words = canon_p.split()
        suggested_pattern = " ".join(words[:2]) if len(words) >= 2 else canon_p
    elif payload.pattern_type == "regex":
        suggested_pattern = re.escape(canon_p)
    else:
        suggested_pattern = canon_p

    target_account = contra_account or "Expenses:Unallocated"

    # Count retroactive matches across staged transactions
    all_payees = db.execute("SELECT payee FROM staged_transactions").fetchall()
    matches = 0
    for (p,) in all_payees:
        cp = canonical_payee(p)
        if payload.pattern_type == "exact" and cp == suggested_pattern:
            matches += 1
        elif payload.pattern_type == "prefix" and cp.startswith(suggested_pattern):
            matches += 1
        elif payload.pattern_type == "regex":
            try:
                if re.search(suggested_pattern, cp):
                    matches += 1
            except Exception:
                pass

    return RuleCandidateResponse(
        suggested_pattern=suggested_pattern,
        target_account=target_account,
        confidence=0.90 if matches > 1 else 0.70,
        retroactive_matches=matches,
    )


@router.get("/{rule_id}/drift", response_model=RuleDriftResponse)
def get_rule_drift(
    rule_id: str,
    db: sqlite3.Connection = Depends(get_db),
):
    """Compute Hit Confidence Trend (HCT) and drift metrics for a rule."""
    rule_row = db.execute(
        "SELECT match_type, pattern, target_account, active FROM categorization_rules WHERE rule_id = ?",
        (rule_id,),
    ).fetchone()
    if not rule_row:
        raise HTTPException(status_code=404, detail="Rule not found")

    match_type, pattern, target_acc, active = rule_row

    # Count audit hits
    audit_hits = db.execute(
        "SELECT count(*) FROM audit_events WHERE action LIKE ? AND result = 'ok'",
        (f"%rule {rule_id}%",),
    ).fetchone()[0]

    # Count matching staged transactions
    all_stx = db.execute(
        "SELECT st.staged_transaction_id, st.payee, con.account "
        "FROM staged_transactions st "
        "JOIN staged_postings con ON con.staged_transaction_id = st.staged_transaction_id AND con.role = 'contra'"
    ).fetchall()

    total_matches = 0
    overrides = 0
    for _, payee, actual_con_acc in all_stx:
        cp = canonical_payee(payee)
        matched = False
        if match_type == "exact" and cp == pattern:
            matched = True
        elif match_type == "prefix" and cp.startswith(pattern):
            matched = True
        elif match_type == "regex":
            try:
                if re.search(pattern, cp):
                    matched = True
            except Exception:
                pass

        if matched:
            total_matches += 1
            if actual_con_acc and actual_con_acc != target_acc:
                overrides += 1

    total_hits = max(audit_hits, total_matches)
    override_rate = round(overrides / max(total_hits, 1), 3)

    if total_hits == 0:
        drift_status = "stale"
    elif override_rate >= 0.15:
        drift_status = "warning"
    else:
        drift_status = "healthy"

    confidence_trend = round(1.0 - override_rate, 2)

    return RuleDriftResponse(
        rule_id=rule_id,
        rule_name=f"{match_type.upper()}: {pattern} -> {target_acc}",
        total_hits=total_hits,
        recent_hits=min(total_hits, 10),
        override_count=overrides,
        override_rate=override_rate,
        confidence_trend=confidence_trend,
        drift_status=drift_status,
    )

