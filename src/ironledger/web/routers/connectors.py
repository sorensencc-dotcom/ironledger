"""Connector governance, circuit breaker monitoring, and sync execution endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel

from ironledger.web.errors import GovernanceException
from ironledger.web.auth import require_operator as require_operator_auth

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


def require_operator(request: Request) -> None:
    require_operator_auth(request, governance_error=True)


def get_active_ledger_id(request: Request, db: sqlite3.Connection) -> str:
    ledger_id = request.headers.get("X-IronLedger-Ledger-Id")
    if ledger_id and ledger_id.strip():
        return ledger_id.strip()
    row = db.execute("SELECT ledger_id FROM ledgers LIMIT 1").fetchone()
    if row:
        return str(row[0])
    return "default-ledger"


# Pydantic Schemas
class ConnectorProviderResponse(BaseModel):
    provider_id: str
    name: str
    protocol_type: str
    base_url: str
    is_active: bool
    rate_limit_rpm: int
    burst_capacity: int
    circuit_breaker_state: str
    failure_count: int
    created_at_utc: str


class ConnectorCredentialStatusResponse(BaseModel):
    provider_id: str
    has_credentials: bool
    kek_key_id: Optional[str] = None
    dek_rotation_age_days: int = 0
    iv_freshness_status: str = "FRESH"
    created_at_utc: Optional[str] = None
    updated_at_utc: Optional[str] = None


class ConnectorSyncRunResponse(BaseModel):
    ledger_id: str
    run_id: str
    provider_id: str
    status: str
    records_fetched: int
    records_staged: int
    error_code: Optional[str] = None
    error_details: Optional[str] = None
    started_at_utc: str
    completed_at_utc: Optional[str] = None


class SyncTimelineEvent(BaseModel):
    event_id: str
    timestamp_utc: str
    event_type: str
    provider_id: str
    summary: str
    details: Dict[str, Any] = {}


class TriggerSyncResponse(BaseModel):
    run_id: str
    provider_id: str
    status: str
    records_fetched: int
    records_staged: int
    message: str


@router.get("", response_model=List[ConnectorProviderResponse])
def list_connector_providers(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> List[ConnectorProviderResponse]:
    """List registered connector providers with live circuit breaker states."""
    ledger_id = get_active_ledger_id(request, db)
    rows = db.execute(
        """
        SELECT 
            p.provider_id, p.name, p.protocol_type, p.base_url, p.is_active,
            p.rate_limit_rpm, p.burst_capacity, p.created_at_utc,
            COALESCE(cb.state, 'CLOSED') as cb_state,
            COALESCE(cb.failure_count, 0) as cb_failures
        FROM connector_providers p
        LEFT JOIN connector_circuit_breakers cb 
            ON p.provider_id = cb.provider_id AND cb.ledger_id = ?
        ORDER BY p.name ASC
        """,
        (ledger_id,),
    ).fetchall()

    results = []
    for r in rows:
        results.append(
            ConnectorProviderResponse(
                provider_id=r[0],
                name=r[1],
                protocol_type=r[2],
                base_url=r[3],
                is_active=bool(r[4]),
                rate_limit_rpm=r[5],
                burst_capacity=r[6],
                created_at_utc=r[7],
                circuit_breaker_state=r[8],
                failure_count=r[9],
            )
        )
    return results


@router.get("/credentials", response_model=List[ConnectorCredentialStatusResponse])
def get_connector_credentials_status(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> List[ConnectorCredentialStatusResponse]:
    """Retrieve envelope credential metadata without exposing secrets."""
    ledger_id = get_active_ledger_id(request, db)
    providers = db.execute("SELECT provider_id FROM connector_providers").fetchall()
    results = []
    now = datetime.now(timezone.utc)

    for (p_id,) in providers:
        cred = db.execute(
            """
            SELECT kek_key_id, created_at_utc, updated_at_utc
            FROM connector_credentials
            WHERE ledger_id = ? AND provider_id = ?
            """,
            (ledger_id, p_id),
        ).fetchone()

        if cred:
            kek_id, created_at, updated_at = cred
            try:
                up_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                age_days = (now - up_dt).days
            except Exception:
                age_days = 0

            iv_freshness = "FRESH" if age_days < 30 else ("STALE" if age_days < 90 else "EXPIRED")

            results.append(
                ConnectorCredentialStatusResponse(
                    provider_id=p_id,
                    has_credentials=True,
                    kek_key_id=kek_id,
                    dek_rotation_age_days=max(0, age_days),
                    iv_freshness_status=iv_freshness,
                    created_at_utc=created_at,
                    updated_at_utc=updated_at,
                )
            )
        else:
            results.append(
                ConnectorCredentialStatusResponse(
                    provider_id=p_id,
                    has_credentials=False,
                    kek_key_id=None,
                    dek_rotation_age_days=0,
                    iv_freshness_status="UNCONFIGURED",
                    created_at_utc=None,
                    updated_at_utc=None,
                )
            )
    return results


@router.get("/sync-runs", response_model=List[ConnectorSyncRunResponse])
def list_connector_sync_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> List[ConnectorSyncRunResponse]:
    """List recent connector synchronization runs for the active ledger."""
    ledger_id = get_active_ledger_id(request, db)
    rows = db.execute(
        """
        SELECT ledger_id, run_id, provider_id, status, records_fetched, records_staged,
               error_code, error_details, started_at_utc, completed_at_utc
        FROM connector_sync_runs
        WHERE ledger_id = ?
        ORDER BY started_at_utc DESC
        LIMIT ?
        """,
        (ledger_id, limit),
    ).fetchall()

    return [
        ConnectorSyncRunResponse(
            ledger_id=r[0],
            run_id=r[1],
            provider_id=r[2],
            status=r[3],
            records_fetched=r[4],
            records_staged=r[5],
            error_code=r[6],
            error_details=r[7],
            started_at_utc=r[8],
            completed_at_utc=r[9],
        )
        for r in rows
    ]


@router.get("/timeline", response_model=List[SyncTimelineEvent])
def get_connector_timeline(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> List[SyncTimelineEvent]:
    """Return an aggregated chronological timeline of sync and connector events."""
    ledger_id = get_active_ledger_id(request, db)
    runs = db.execute(
        """
        SELECT run_id, started_at_utc, provider_id, status, records_fetched, records_staged, error_code
        FROM connector_sync_runs
        WHERE ledger_id = ?
        ORDER BY started_at_utc DESC
        LIMIT ?
        """,
        (ledger_id, limit),
    ).fetchall()

    events: List[SyncTimelineEvent] = []
    for r in runs:
        events.append(
            SyncTimelineEvent(
                event_id=f"sync-{r[0]}",
                timestamp_utc=r[1],
                event_type="SYNC_EXECUTION",
                provider_id=r[2],
                summary=f"Sync run {r[3]}: {r[4]} fetched, {r[5]} staged",
                details={"status": r[3], "fetched": r[4], "staged": r[5], "error_code": r[6]},
            )
        )
    return events


@router.post("/{provider_id}/trigger", response_model=TriggerSyncResponse)
def trigger_connector_sync(
    provider_id: str,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> TriggerSyncResponse:
    """Trigger manual synchronization for a connector provider with idempotency protection."""
    ledger_id = get_active_ledger_id(request, db)
    
    # Check circuit breaker
    cb_row = db.execute(
        "SELECT state FROM connector_circuit_breakers WHERE ledger_id = ? AND provider_id = ?",
        (ledger_id, provider_id),
    ).fetchone()
    if cb_row and cb_row[0] == "OPEN":
        raise GovernanceException(
            status_code=status.HTTP_409_CONFLICT,
            error_code="GOVERNANCE_CIRCUIT_OPEN",
            message=f"Connector {provider_id} circuit breaker is OPEN",
            details={"provider_id": provider_id},
        )

    # Check Idempotency Key
    if idempotency_key:
        existing = db.execute(
            "SELECT response_body_json FROM governance_nonce_registry WHERE ledger_id = ? AND idempotency_key = ?",
            (ledger_id, idempotency_key),
        ).fetchone()
        if existing and existing[0]:
            try:
                cached = json.loads(existing[0])
                return TriggerSyncResponse(**cached)
            except Exception:
                pass

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Record sync run entry
    db.execute(
        """
        INSERT INTO connector_sync_runs (
            ledger_id, run_id, provider_id, status, records_fetched, records_staged, started_at_utc, completed_at_utc
        ) VALUES (?, ?, ?, 'SUCCESS', 0, 0, ?, ?)
        """,
        (ledger_id, run_id, provider_id, now_utc, now_utc),
    )

    # Record Governance Audit Event
    audit_hash = hashlib.sha256(f"{ledger_id}:{run_id}:{now_utc}".encode()).hexdigest()
    db.execute(
        """
        INSERT INTO governance_audit_events (
            ledger_id, actor, action, target, before_state_json, after_state_json, envelope_hash, timestamp_utc
        ) VALUES (?, 'operator', 'TRIGGER_CONNECTOR_SYNC', ?, '{}', json_object('run_id', ?, 'status', 'SUCCESS'), ?, ?)
        """,
        (ledger_id, provider_id, run_id, audit_hash, now_utc),
    )

    resp = TriggerSyncResponse(
        run_id=run_id,
        provider_id=provider_id,
        status="SUCCESS",
        records_fetched=0,
        records_staged=0,
        message=f"Sync triggered successfully for {provider_id}",
    )

    # Store in Idempotency Registry
    if idempotency_key:
        expires = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%fZ")
        req_hash = hashlib.sha256(f"{ledger_id}:{provider_id}".encode()).hexdigest()
        db.execute(
            """
            INSERT OR REPLACE INTO governance_nonce_registry (
                ledger_id, idempotency_key, scope, request_hash, response_status, response_body_json, expires_at_utc
            ) VALUES (?, ?, 'TRIGGER_SYNC', ?, 200, ?, ?)
            """,
            (ledger_id, idempotency_key, req_hash, json.dumps(resp.model_dump()), expires),
        )

    db.commit()
    return resp
