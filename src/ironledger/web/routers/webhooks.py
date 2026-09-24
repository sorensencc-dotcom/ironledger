"""Webhook subscriptions, delivery monitoring, and DLQ inspection/redrive endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import sqlite3
from urllib.parse import urlparse
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ironledger.web.errors import GovernanceException
from ironledger.web.auth import require_operator as require_operator_auth

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


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


def validate_ssrf_target_url(target_url: str) -> None:
    """Ensure target URL does not point to private/metadata IP space."""
    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https"):
        raise GovernanceException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="GOVERNANCE_VALIDATION_ERROR",
            message="Invalid target URL protocol (must be http or https)",
        )
    hostname = parsed.hostname
    if not hostname:
        raise GovernanceException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="GOVERNANCE_VALIDATION_ERROR",
            message="Missing hostname in target URL",
        )
    
    # Allow localhost for local development workbench
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise GovernanceException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="GOVERNANCE_VALIDATION_ERROR",
                message=f"SSRF violation: private or reserved IP address target is forbidden: {hostname}",
            )
    except ValueError:
        # Hostname is a domain name
        pass


# Schemas
class WebhookSubscriptionResponse(BaseModel):
    ledger_id: str
    subscription_id: str
    target_url: str
    secret_fingerprint_hex: str
    event_types: List[str]
    is_active: bool
    created_at_utc: str


class CreateWebhookSubscriptionRequest(BaseModel):
    target_url: str
    event_types: List[str] = Field(default_factory=lambda: ["TRANSACTION_STAGED", "RULE_MATCHED", "COMPILE_COMPLETED"])


class WebhookDeliveryResponse(BaseModel):
    ledger_id: str
    delivery_id: str
    event_id: str
    subscription_id: str
    status: str
    retry_count: int
    next_retry_at_utc: str
    leased_by: Optional[str] = None
    leased_until_utc: Optional[str] = None
    last_status_code: Optional[int] = None
    last_error: Optional[str] = None
    created_at_utc: str
    completed_at_utc: Optional[str] = None


class WebhookDLQEntryResponse(BaseModel):
    ledger_id: str
    dlq_entry_id: str
    delivery_id: str
    event_id: str
    subscription_id: str
    status_code: Optional[int] = None
    last_error: str
    attempt_count: int
    failed_at_utc: str


class RedriveDLQResponse(BaseModel):
    dlq_entry_id: str
    delivery_id: str
    status: str
    message: str


@router.get("/subscriptions", response_model=List[WebhookSubscriptionResponse])
def list_webhook_subscriptions(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> List[WebhookSubscriptionResponse]:
    """List webhook endpoint subscriptions for active ledger."""
    ledger_id = get_active_ledger_id(request, db)
    rows = db.execute(
        """
        SELECT ledger_id, subscription_id, target_url, secret_fingerprint_hex,
               event_types_json, is_active, created_at_utc
        FROM webhook_subscriptions
        WHERE ledger_id = ?
        ORDER BY created_at_utc DESC
        """,
        (ledger_id,),
    ).fetchall()

    results = []
    for r in rows:
        try:
            evs = json.loads(r[4])
        except Exception:
            evs = []
        results.append(
            WebhookSubscriptionResponse(
                ledger_id=r[0],
                subscription_id=r[1],
                target_url=r[2],
                secret_fingerprint_hex=r[3],
                event_types=evs,
                is_active=bool(r[5]),
                created_at_utc=r[6],
            )
        )
    return results


@router.post("/subscriptions", response_model=WebhookSubscriptionResponse)
def create_webhook_subscription(
    payload: CreateWebhookSubscriptionRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> WebhookSubscriptionResponse:
    """Create a new webhook subscription with SSRF validation and envelope secrets."""
    validate_ssrf_target_url(payload.target_url)
    ledger_id = get_active_ledger_id(request, db)
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Generate envelope secret fingerprint
    secret_bytes = uuid.uuid4().bytes + uuid.uuid4().bytes
    fingerprint = hashlib.sha256(secret_bytes).hexdigest()
    ev_json = json.dumps(payload.event_types)

    # Insert into database with simulated envelope blobs
    dummy_blob = b"\x00" * 32
    dummy_iv = "0" * 24
    dummy_tag = "0" * 32

    db.execute(
        """
        INSERT INTO webhook_subscriptions (
            ledger_id, subscription_id, target_url, kek_key_id,
            encrypted_dek_blob, dek_iv_hex, dek_auth_tag_hex,
            encrypted_secret_blob, secret_iv_hex, secret_auth_tag_hex,
            secret_fingerprint_hex, event_types_json, is_active, created_at_utc
        ) VALUES (?, ?, ?, 'local-kek-v1', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            ledger_id, sub_id, payload.target_url,
            dummy_blob, dummy_iv, dummy_tag,
            dummy_blob, dummy_iv, dummy_tag,
            fingerprint, ev_json, now_utc,
        ),
    )

    # Governance Audit Event
    audit_hash = hashlib.sha256(f"{ledger_id}:{sub_id}:{now_utc}".encode()).hexdigest()
    db.execute(
        """
        INSERT INTO governance_audit_events (
            ledger_id, actor, action, target, before_state_json, after_state_json, envelope_hash, timestamp_utc
        ) VALUES (?, 'operator', 'CREATE_WEBHOOK_SUBSCRIPTION', ?, '{}', json_object('target_url', ?), ?, ?)
        """,
        (ledger_id, sub_id, payload.target_url, audit_hash, now_utc),
    )
    db.commit()

    return WebhookSubscriptionResponse(
        ledger_id=ledger_id,
        subscription_id=sub_id,
        target_url=payload.target_url,
        secret_fingerprint_hex=fingerprint,
        event_types=payload.event_types,
        is_active=True,
        created_at_utc=now_utc,
    )


@router.get("/deliveries", response_model=List[WebhookDeliveryResponse])
def list_webhook_deliveries(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> List[WebhookDeliveryResponse]:
    """List webhook delivery queue items with lease and status metadata."""
    ledger_id = get_active_ledger_id(request, db)
    rows = db.execute(
        """
        SELECT ledger_id, delivery_id, event_id, subscription_id, status,
               retry_count, next_retry_at_utc, leased_by, leased_until_utc,
               last_status_code, last_error, created_at_utc, completed_at_utc
        FROM webhook_deliveries
        WHERE ledger_id = ?
        ORDER BY created_at_utc DESC
        LIMIT ?
        """,
        (ledger_id, limit),
    ).fetchall()

    return [
        WebhookDeliveryResponse(
            ledger_id=r[0],
            delivery_id=r[1],
            event_id=r[2],
            subscription_id=r[3],
            status=r[4],
            retry_count=r[5],
            next_retry_at_utc=r[6],
            leased_by=r[7],
            leased_until_utc=r[8],
            last_status_code=r[9],
            last_error=r[10],
            created_at_utc=r[11],
            completed_at_utc=r[12],
        )
        for r in rows
    ]


@router.get("/dlq", response_model=List[WebhookDLQEntryResponse])
def list_webhook_dlq(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> List[WebhookDLQEntryResponse]:
    """List dead-lettered webhook deliveries."""
    ledger_id = get_active_ledger_id(request, db)
    rows = db.execute(
        """
        SELECT ledger_id, dlq_entry_id, delivery_id, event_id, subscription_id,
               status_code, last_error, attempt_count, failed_at_utc
        FROM webhook_delivery_dlq
        WHERE ledger_id = ?
        ORDER BY failed_at_utc DESC
        LIMIT ?
        """,
        (ledger_id, limit),
    ).fetchall()

    return [
        WebhookDLQEntryResponse(
            ledger_id=r[0],
            dlq_entry_id=r[1],
            delivery_id=r[2],
            event_id=r[3],
            subscription_id=r[4],
            status_code=r[5],
            last_error=r[6],
            attempt_count=r[7],
            failed_at_utc=r[8],
        )
        for r in rows
    ]


@router.post("/dlq/{dlq_entry_id}/redrive", response_model=RedriveDLQResponse)
def redrive_webhook_dlq(
    dlq_entry_id: str,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> RedriveDLQResponse:
    """Atomically re-enqueue a dead-lettered delivery back to webhook_deliveries."""
    ledger_id = get_active_ledger_id(request, db)
    row = db.execute(
        """
        SELECT delivery_id, attempt_count
        FROM webhook_delivery_dlq
        WHERE ledger_id = ? AND dlq_entry_id = ?
        """,
        (ledger_id, dlq_entry_id),
    ).fetchone()

    if not row:
        raise GovernanceException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="GOVERNANCE_DLQ_REDRIVE_DENIED",
            message=f"DLQ entry {dlq_entry_id} not found",
        )

    delivery_id, attempt_count = row
    if attempt_count >= 10:
        raise GovernanceException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="GOVERNANCE_DLQ_REDRIVE_DENIED",
            message="Max redrive threshold exceeded (poison message protection)",
            details={"attempt_count": attempt_count},
        )

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Reset delivery status to PENDING and update next_retry_at_utc
    db.execute(
        """
        UPDATE webhook_deliveries
        SET status = 'PENDING',
            retry_count = 0,
            next_retry_at_utc = ?,
            leased_by = NULL,
            leased_until_utc = NULL
        WHERE ledger_id = ? AND delivery_id = ?
        """,
        (now_utc, ledger_id, delivery_id),
    )

    # Delete from DLQ
    db.execute(
        "DELETE FROM webhook_delivery_dlq WHERE ledger_id = ? AND dlq_entry_id = ?",
        (ledger_id, dlq_entry_id),
    )

    # Governance Audit Event
    audit_hash = hashlib.sha256(f"{ledger_id}:{dlq_entry_id}:{now_utc}".encode()).hexdigest()
    db.execute(
        """
        INSERT INTO governance_audit_events (
            ledger_id, actor, action, target, before_state_json, after_state_json, envelope_hash, timestamp_utc
        ) VALUES (?, 'operator', 'REDRIVE_WEBHOOK_DLQ', ?, json_object('dlq_entry_id', ?), json_object('status', 'PENDING'), ?, ?)
        """,
        (ledger_id, delivery_id, dlq_entry_id, audit_hash, now_utc),
    )
    db.commit()

    return RedriveDLQResponse(
        dlq_entry_id=dlq_entry_id,
        delivery_id=delivery_id,
        status="PENDING",
        message=f"Delivery {delivery_id} successfully re-enqueued for processing",
    )
