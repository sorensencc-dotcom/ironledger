"""System state, safe-mode status, and audit log endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, Request

from ironledger.cli.auth import safe_mode_enabled
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
        "SELECT event_id, sequence_number, timestamp_utc, actor, action, target, result, event_hash "
        "FROM audit_events ORDER BY sequence_number DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        {
            "event_id": r[0],
            "sequence_number": r[1],
            "timestamp_utc": r[2],
            "actor": r[3],
            "action": r[4],
            "target": r[5],
            "result": r[6],
            "event_hash": r[7],
        }
        for r in rows
    ]

