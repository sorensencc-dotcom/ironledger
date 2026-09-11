"""System state, safe-mode status, and audit log endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, Request

from ironledger.governance.safemode import safe_mode_enabled
from ironledger.web.schemas import SafeModeStatusResponse

router = APIRouter(prefix="/api/system", tags=["system"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


@router.get("/safe-mode", response_model=SafeModeStatusResponse)
def get_safe_mode_status(
    request: Request,
) -> SafeModeStatusResponse:
    """Retrieve safe mode gating status and token requirements."""
    config_dir = getattr(request.app.state, "config_dir", Path("config"))
    is_safe = safe_mode_enabled(config_dir)

    return SafeModeStatusResponse(
        enabled=is_safe,
        token_required=is_safe,
        token_active=False,
        token_expires_at=None,
    )


@router.get("/audit")
def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve append-only audit trail records."""
    rows = db.execute(
        "SELECT seq, ts_utc, actor, action, target, result, event_hash "
        "FROM audit_events ORDER BY seq DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return {
        "events": [
            {
                "sequence_number": r[0],
                "timestamp_utc": r[1],
                "actor": r[2],
                "action": r[3],
                "target": r[4],
                "result": r[5],
                "event_hash": r[6],
            }
            for r in rows
        ]
    }


@router.get("/mutations")
def get_mutation_log(
    limit: int = 50,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve append-only meta-ledger mutation records."""
    try:
        rows = db.execute(
            "SELECT seq, mutation_id, ts_utc, operator_session, action, staged_count, "
            "rules_applied, rules_created, sha256_before, sha256_after, prev_mutation_hash, mutation_hash "
            "FROM mutation_events ORDER BY seq DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return {
            "mutations": [
                {
                    "seq": r[0],
                    "mutation_id": r[1],
                    "ts_utc": r[2],
                    "operator_session": r[3],
                    "action": r[4],
                    "staged_count": r[5],
                    "rules_applied": r[6],
                    "rules_created": r[7],
                    "sha256_before": r[8],
                    "sha256_after": r[9],
                    "prev_mutation_hash": r[10],
                    "mutation_hash": r[11],
                }
                for r in rows
            ]
        }
    except sqlite3.OperationalError:
        return {"mutations": []}


