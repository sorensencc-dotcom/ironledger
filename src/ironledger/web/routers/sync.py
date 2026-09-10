"""Sync status and poll endpoints for IronLedger Operator Workbench."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ironledger.pipeline import sync_daemon
from ironledger.pipeline.sync_daemon import SyncLockActiveError, acquire_lock, release_lock
from ironledger.security import secrets
from ironledger.security.secrets import CredentialsNotFoundError, get_access_url

__all__ = ["router", "SyncStatusResponse", "SyncPollResponse"]

router = APIRouter(prefix="/api/sync", tags=["sync"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


def require_operator(request: Request) -> None:
    op_token = getattr(request.app.state, "op_token", None)
    if op_token is None:
        return
    if request.headers.get("X-IronLedger-Op-Token") != op_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_csrf(request: Request) -> None:
    if not request.headers.get("X-CSRF-Token"):
        raise HTTPException(status_code=400, detail="Missing X-CSRF-Token header")


class SyncStatusResponse(BaseModel):
    state: str
    pending_count: int
    last_error_code: Optional[str] = None


class SyncPollResponse(BaseModel):
    inserted: int
    skipped: int


@router.get("/status", response_model=SyncStatusResponse)
def sync_status(
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> SyncStatusResponse:
    pending = db.execute(
        "SELECT COUNT(*) FROM staged_transactions WHERE status='pending'"
    ).fetchone()[0]
    try:
        secrets.get_access_url(db)
        state = "HEALTHY"
    except secrets.CredentialsNotFoundError:
        state = "UNCONFIGURED"
    except Exception:
        state = "DEGRADED"
    return SyncStatusResponse(state=state, pending_count=pending)


@router.post("/poll", response_model=SyncPollResponse)
def sync_poll(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
    _csrf=Depends(require_csrf),
) -> SyncPollResponse:
    from ironledger.ingest.formats.simplefin import fetch_accounts
    from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload

    lock_path = Path(request.app.state.db_path).parent / ".sync.lock"
    try:
        sync_daemon.acquire_lock(lock_path)
    except sync_daemon.SyncLockActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        end_dt = datetime.now(timezone.utc)
        ev_dir = Path(request.app.state.db_path).parent / "evidence" / "source_documents"
        payload = fetch_accounts(
            db,
            start_date=end_dt - timedelta(days=30),
            end_date=end_dt,
            evidence_dir=ev_dir,
        )
        account_map = dict(
            db.execute(
                "SELECT remote_account_id, canonical_account FROM simplefin_account_map"
            ).fetchall()
        )
        ins, skip = ingest_simplefin_payload(
            db, payload, evidence_path=ev_dir, account_map=account_map
        )
        return SyncPollResponse(inserted=ins, skipped=skip)
    finally:
        sync_daemon.release_lock(lock_path)
