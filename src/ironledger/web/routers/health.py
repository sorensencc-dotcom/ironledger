"""Health and readiness probe endpoints for Kubernetes / container orchestration."""

from __future__ import annotations

import sqlite3
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(tags=["health"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


@router.get("/healthz", status_code=status.HTTP_200_OK)
def liveness_probe() -> dict[str, str]:
    """Liveness probe returning 200 OK if service process is active."""
    return {"status": "ok", "service": "ironledger"}


@router.get("/readyz", status_code=status.HTTP_200_OK)
def readiness_probe(request: Request) -> dict[str, Any]:
    """Readiness probe verifying database connectivity and query execution."""
    try:
        conn = request.app.state.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        res = cursor.fetchone()
        if not res or res[0] != 1:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database query returned unexpected result",
            )
        return {
            "status": "ready",
            "database": "connected",
            "service": "ironledger",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connectivity check failed: {exc}",
        )
