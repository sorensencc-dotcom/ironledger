"""Sync status and poll endpoints for IronLedger Operator Workbench."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ironledger.pipeline import sync_daemon
from ironledger.security import secrets

__all__ = [
    "router",
    "SyncStatusResponse",
    "SyncPollResponse",
    "generate_csrf_token",
    "verify_csrf_token",
]

router = APIRouter(prefix="/api/sync", tags=["sync"])


def generate_csrf_token(
    op_token: str,
    *,
    now_epoch: int | None = None,
    ttl_seconds: int = 3600,
) -> str:
    """Generate a signed, timestamped CSRF token bound to the operator token."""
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    ts_hex = hex(now)[2:]
    msg = f"{ts_hex}:ironledger-csrf".encode("utf-8")
    sig = hmac.new(op_token.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{ts_hex}.{sig}"


def verify_csrf_token(
    csrf_token: str,
    op_token: str,
    *,
    now_epoch: int | None = None,
    max_ttl: int = 3600,
) -> bool:
    """Verify that a CSRF token is valid, unexpired, and cryptographically bound to op_token."""
    if not isinstance(csrf_token, str) or "." not in csrf_token:
        return False
    parts = csrf_token.split(".", 1)
    if len(parts) != 2:
        return False
    ts_hex, sig = parts
    try:
        ts = int(ts_hex, 16)
    except ValueError:
        return False

    now = int(time.time()) if now_epoch is None else int(now_epoch)
    # Expiration and future clock-skew checks (30s skew allowed)
    if ts > now + 30 or (now - ts) > max_ttl:
        return False

    msg = f"{ts_hex}:ironledger-csrf".encode("utf-8")
    expected_sig = hmac.new(op_token.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


def require_operator(request: Request) -> None:
    op_token = getattr(request.app.state, "op_token", None)
    if not op_token or not isinstance(op_token, str) or not op_token.strip():
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = request.headers.get("X-IronLedger-Op-Token")
    if not token or not hmac.compare_digest(token, op_token.strip()):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_csrf(request: Request) -> None:
    csrf_token = request.headers.get("X-CSRF-Token")
    if not csrf_token:
        raise HTTPException(status_code=400, detail="Missing X-CSRF-Token header")
    op_token = getattr(request.app.state, "op_token", None)
    if not op_token or not isinstance(op_token, str) or not op_token.strip():
        raise HTTPException(status_code=401, detail="Unauthorized")

    static_csrf = getattr(request.app.state, "csrf_token", None)
    if static_csrf and isinstance(static_csrf, str) and hmac.compare_digest(csrf_token, static_csrf):
        return

    if not verify_csrf_token(csrf_token, op_token.strip()):
        raise HTTPException(status_code=403, detail="Invalid or expired CSRF token")


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
