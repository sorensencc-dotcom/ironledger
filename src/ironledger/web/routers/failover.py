"""FastAPI router for High-Availability failover, node heartbeats, and tenant key rotation."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ironledger.federation.election import (
    LeaderElectionEngine,
    LeaderFencedError,
)
from ironledger.federation.heartbeat import (
    HeartbeatMonitor,
)
from ironledger.security.rotation import (
    KeyRotationError,
    TenantKeyRotationEngine,
)

router = APIRouter(prefix="/api/v1", tags=["Failover & High Availability"])


def get_db(request: Request) -> sqlite3.Connection:
    conn_func = getattr(request.app.state, "get_db", None)
    if conn_func:
        return conn_func()
    db_path = getattr(request.app.state, "db_path", "ironledger.db")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


class HeartbeatRequest(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=64)


class PromotionRequest(BaseModel):
    cluster_id: str = Field(..., min_length=1, max_length=64)
    candidate_node_id: str = Field(..., min_length=1, max_length=64)
    lease_seconds: int = Field(default=15, ge=5, le=3600)


class KeyRotationRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    new_kek_key_id: str = Field(..., min_length=1, max_length=64)
    rotated_by: str = Field(default="operator", min_length=1, max_length=64)


@router.get("/failover/status")
def get_failover_status(
    cluster_id: str = Query(default="default"),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve cluster primary lease, node staleness, and quorum state."""
    lease = LeaderElectionEngine.get_current_lease(conn, cluster_id)
    nodes = HeartbeatMonitor.get_cluster_nodes(conn, cluster_id)
    
    total_nodes = len(nodes)
    active_nodes = len([n for n in nodes if n.is_active and not n.is_stale])
    has_quorum = active_nodes >= (total_nodes // 2 + 1) if total_nodes > 0 else False

    return {
        "cluster_id": cluster_id,
        "has_quorum": has_quorum,
        "total_nodes": total_nodes,
        "active_nodes": active_nodes,
        "active_lease": {
            "term": lease.term,
            "leader_node_id": lease.leader_node_id,
            "fence_token": lease.lease_fence_token,
            "acquired_at_utc": lease.lease_acquired_at_utc,
            "expires_at_utc": lease.lease_expires_at_utc,
            "is_expired": lease.is_expired,
        } if lease else None,
        "nodes": [
            {
                "node_id": n.node_id,
                "cluster_id": n.cluster_id,
                "endpoint_url": n.endpoint_url,
                "role": n.role,
                "last_heartbeat_utc": n.last_heartbeat_utc,
                "is_active": n.is_active,
                "is_stale": n.is_stale,
            }
            for n in nodes
        ],
    }


@router.post("/failover/heartbeat")
def post_heartbeat(
    req: HeartbeatRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Record heartbeat timestamp for a registered cluster node."""
    success = HeartbeatMonitor.record_heartbeat(conn, req.node_id)
    conn.commit()
    if not success:
        raise HTTPException(status_code=404, detail=f"Node '{req.node_id}' not found")
    return {"status": "RECORDED", "node_id": req.node_id}


@router.post("/failover/promote")
def post_promote_leader(
    req: PromotionRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Manually or automatically promote a candidate node to cluster PRIMARY."""
    promoted, lease = HeartbeatMonitor.check_and_promote(
        conn=conn,
        cluster_id=req.cluster_id,
        candidate_node_id=req.candidate_node_id,
        lease_seconds=req.lease_seconds,
    )
    conn.commit()
    if not promoted or lease is None:
        raise HTTPException(
            status_code=409,
            detail=f"Promotion failed: active leader lease held by another node in cluster '{req.cluster_id}'",
        )

    return {
        "status": "PROMOTED",
        "cluster_id": req.cluster_id,
        "leader_node_id": lease.leader_node_id,
        "term": lease.term,
        "fence_token": lease.lease_fence_token,
        "expires_at_utc": lease.lease_expires_at_utc,
    }


@router.post("/security/rotate-key")
def post_rotate_key(
    req: KeyRotationRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Execute zero-downtime tenant KEK rotation and re-wrap all stored secrets."""
    try:
        result = TenantKeyRotationEngine.rotate_tenant_kek(
            conn=conn,
            tenant_id=req.tenant_id,
            new_kek_key_id=req.new_kek_key_id,
            rotated_by=req.rotated_by,
        )
        return result
    except KeyRotationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
