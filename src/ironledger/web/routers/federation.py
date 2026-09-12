"""FastAPI router for multi-tenant federation and event stream governance."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ironledger.db.connection import connect
from ironledger.events.dispatcher import OutboxDispatcher
from ironledger.events.envelope import (
    EventEnvelopeError,
    FederatedEvent,
    validate_federated_event,
)
from ironledger.web.errors import GovernanceException



router = APIRouter(prefix="/api/federation", tags=["federation"])


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    default_ledger_id: str = Field(default="default", min_length=1, max_length=64)


class ClusterNodeRegisterRequest(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=64)
    cluster_id: str = Field(..., min_length=1, max_length=64)
    endpoint_url: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(PRIMARY|REPLICA|WITNESS)$")


class PeerEventIngestRequest(BaseModel):
    cluster_id: str = Field(..., min_length=1)
    event: dict[str, Any]


@router.get("/tenants")
def list_tenants(request: Request) -> list[dict[str, Any]]:
    """List registered federation tenant domains."""
    db_path = request.app.state.db_path
    conn = connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT tenant_id, name, default_ledger_id, is_active, created_at_utc
            FROM federation_tenants
            ORDER BY created_at_utc ASC
            """
        )
        return [
            {
                "tenant_id": r[0],
                "name": r[1],
                "default_ledger_id": r[2],
                "is_active": bool(r[3]),
                "created_at_utc": r[4],
            }
            for r in cursor.fetchall()
        ]
    finally:
        conn.close()


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreateRequest, request: Request) -> dict[str, Any]:
    """Register a new multi-tenant domain."""
    db_path = request.app.state.db_path
    conn = connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO federation_tenants (tenant_id, name, default_ledger_id)
            VALUES (?, ?, ?)
            """,
            (payload.tenant_id, payload.name, payload.default_ledger_id),
        )
        conn.commit()
        return {
            "tenant_id": payload.tenant_id,
            "name": payload.name,
            "default_ledger_id": payload.default_ledger_id,
            "status": "CREATED",
        }
    except sqlite3.IntegrityError as exc:
        raise GovernanceException(
            status_code=status.HTTP_409_CONFLICT,
            error_code="GOVERNANCE_STATE_CONFLICT",
            message=f"Tenant ID '{payload.tenant_id}' already exists or ledger is invalid: {exc}",
        )

    finally:
        conn.close()


@router.get("/nodes")
def list_cluster_nodes(request: Request) -> list[dict[str, Any]]:
    """List peer cluster node topologies and heartbeats."""
    db_path = request.app.state.db_path
    conn = connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT node_id, cluster_id, endpoint_url, role, last_heartbeat_utc, is_active, created_at_utc
            FROM federation_cluster_nodes
            ORDER BY cluster_id, node_id
            """
        )
        return [
            {
                "node_id": r[0],
                "cluster_id": r[1],
                "endpoint_url": r[2],
                "role": r[3],
                "last_heartbeat_utc": r[4],
                "is_active": bool(r[5]),
                "created_at_utc": r[6],
            }
            for r in cursor.fetchall()
        ]
    finally:
        conn.close()


@router.post("/nodes", status_code=status.HTTP_200_OK)
def register_cluster_node(payload: ClusterNodeRegisterRequest, request: Request) -> dict[str, Any]:
    """Register or update heartbeat for a cluster node."""
    from datetime import datetime, timezone

    db_path = request.app.state.db_path
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO federation_cluster_nodes (
                node_id, cluster_id, endpoint_url, role, last_heartbeat_utc
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                cluster_id = excluded.cluster_id,
                endpoint_url = excluded.endpoint_url,
                role = excluded.role,
                last_heartbeat_utc = excluded.last_heartbeat_utc,
                is_active = 1
            """,
            (payload.node_id, payload.cluster_id, payload.endpoint_url, payload.role, now_utc),
        )
        conn.commit()
        return {
            "node_id": payload.node_id,
            "cluster_id": payload.cluster_id,
            "role": payload.role,
            "last_heartbeat_utc": now_utc,
            "status": "REGISTERED",
        }
    finally:
        conn.close()


@router.get("/events")
def list_federated_events(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """Query paged federated event outbox stream."""
    db_path = request.app.state.db_path
    conn = connect(db_path)
    try:
        cursor = conn.cursor()
        query = """
            SELECT seq, event_id, tenant_id, ledger_id, event_type, source, severity,
                   payload_json, metadata_json, published_to_peers, created_at_utc
            FROM federated_event_outbox
            WHERE 1=1
        """
        params: list[Any] = []
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        if source:
            query += " AND source = ?"
            params.append(source)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        query += " ORDER BY seq DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, tuple(params))
        return [
            {
                "seq": r[0],
                "event_id": r[1],
                "tenant_id": r[2],
                "ledger_id": r[3],
                "event_type": r[4],
                "source": r[5],
                "severity": r[6],
                "payload": json.loads(r[7]),
                "metadata": json.loads(r[8]),
                "published_to_peers": bool(r[9]),
                "created_at_utc": r[10],
            }
            for r in cursor.fetchall()
        ]
    finally:
        conn.close()


@router.post("/events/ingest", status_code=status.HTTP_200_OK)
def ingest_peer_event(payload: PeerEventIngestRequest, request: Request) -> dict[str, Any]:
    """Idempotently ingest an event from a peer cluster node."""
    try:
        event = FederatedEvent(
            event_id=payload.event["event_id"],
            event_type=payload.event["event_type"],
            occurred_at=payload.event["occurred_at"],
            recorded_at=payload.event["recorded_at"],
            tenant_id=payload.event["tenant_id"],
            ledger_id=payload.event["ledger_id"],
            source=payload.event["source"],
            severity=payload.event["severity"],
            payload=payload.event["payload"],
            metadata=payload.event.get("metadata", {}),
        )
    except (KeyError, TypeError) as exc:
        raise GovernanceException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="GOVERNANCE_VALIDATION_ERROR",
            message=f"Malformed event payload: {exc}",
        )

    db_path = request.app.state.db_path
    conn = connect(db_path)
    try:
        accepted = OutboxDispatcher.ingest_peer_event(conn, payload.cluster_id, event)
        conn.commit()
        return {
            "cluster_id": payload.cluster_id,
            "event_id": event.event_id,
            "status": "ACCEPTED" if accepted else "DUPLICATE_IGNORED",
        }
    except EventEnvelopeError as exc:
        raise GovernanceException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="GOVERNANCE_VALIDATION_ERROR",
            message=str(exc),
        )
    finally:
        conn.close()

