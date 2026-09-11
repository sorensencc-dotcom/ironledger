"""Projection queries (balances, FTS search) and freshness latency verification."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ironledger.governance.safemode import (
    SafeModeAuthorizationError,
    require_governed_authorization,
    safe_mode_enabled,
)
from ironledger.project.errors import ProjectError, ProjectInputError, ProjectStaleError
from ironledger.project.query import assert_fresh, balances as get_proj_balances, search as search_proj
from ironledger.web.schemas import BalanceItemResponse, FreshnessResponse

router = APIRouter(prefix="/api", tags=["projection"])


def get_proj_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_projection_db()


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


@router.get("/balances", response_model=List[BalanceItemResponse])
def list_balances(
    proj_db: sqlite3.Connection = Depends(get_proj_db),
) -> List[BalanceItemResponse]:
    """Retrieve all account balances from the active projection."""
    try:
        rows = get_proj_balances(proj_db)
        results: list[BalanceItemResponse] = []
        for r in rows:
            scale = r.minor_unit_scale
            if scale == 0:
                formatted = f"{r.minor_units}"
            else:
                divisor = 10**scale
                val = r.minor_units / divisor
                formatted = f"{val:.{scale}f}"

            results.append(
                BalanceItemResponse(
                    account=r.account,
                    currency=r.currency,
                    minor_units=r.minor_units,
                    scale=scale,
                    formatted_amount=formatted,
                )
            )
        return results
    except sqlite3.OperationalError:
        return []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Projection balances query failed: {exc}") from exc


@router.get("/search")
def search_entries(
    q: str = Query(..., description="FTS search query"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    proj_db: sqlite3.Connection = Depends(get_proj_db),
):
    """Full-text search across entry payees, narrations, accounts, and postings."""
    try:
        hits = search_proj(proj_db, q, limit=limit, offset=offset)
        return [
            {
                "entry_date": h.entry_date,
                "payee": h.payee,
                "narration": h.narration,
                "account": h.account,
                "minor_units": h.minor_units,
                "currency": h.currency,
                "staged_transaction_id": h.staged_transaction_id,
                "posting_id": h.posting_id,
            }
            for h in hits
        ]
    except ProjectInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc


@router.get("/projection/freshness", response_model=FreshnessResponse)
def check_freshness(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> FreshnessResponse:
    """Verify projection freshness against ledger on disk and calculate latency."""
    app_state = request.app.state
    ledger_dir = getattr(app_state, "ledger_dir", Path("ledger"))
    projection_dir = getattr(app_state, "projection_dir", Path("projection"))

    last_compile_ts: Optional[str] = None
    last_proj_ts: Optional[str] = None

    # Fetch latest successful compile run timestamp
    try:
        compile_row = db.execute(
            "SELECT finished_at_utc FROM compile_runs WHERE status = 'succeeded' "
            "ORDER BY finished_at_utc DESC LIMIT 1"
        ).fetchone()
        if compile_row:
            last_compile_ts = compile_row[0]
    except Exception:
        pass

    # Check projection freshness
    try:
        proj_conn = assert_fresh(ledger_dir, projection_dir)
        meta_row = proj_conn.execute(
            "SELECT built_at_utc FROM projection_meta WHERE singleton = 1"
        ).fetchone()
        if meta_row:
            last_proj_ts = meta_row[0]
        proj_conn.close()

        latency = 0.0
        if last_compile_ts and last_proj_ts:
            try:
                t1 = datetime.fromisoformat(last_compile_ts.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(last_proj_ts.replace("Z", "+00:00"))
                latency = max(0.0, abs((t2 - t1).total_seconds()))
            except Exception:
                pass

        status_str = "fresh" if latency < 10.0 else "stale"

        return FreshnessResponse(
            is_fresh=True,
            latency_seconds=latency,
            last_compile_timestamp=last_compile_ts,
            last_projection_timestamp=last_proj_ts,
            status=status_str,
        )
    except ProjectStaleError:
        return FreshnessResponse(
            is_fresh=False,
            latency_seconds=999.0,
            last_compile_timestamp=last_compile_ts,
            last_projection_timestamp=last_proj_ts,
            status="stale",
        )
    except Exception:
        return FreshnessResponse(
            is_fresh=False,
            latency_seconds=9999.0,
            last_compile_timestamp=last_compile_ts,
            last_projection_timestamp=None,
            status="critical",
        )

