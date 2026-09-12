"""Analytics and portfolio reporting endpoints for IronLedger."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


@router.get("/sankey")
def get_sankey_data(
    period: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="Billing period formatted as YYYY-MM"),
    conn: sqlite3.Connection = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve categorized directed cash flow links for Sankey visualization."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT source_node, target_node, amount_minor_units 
            FROM v_sankey_cash_flows 
            WHERE period_month = ?
            ORDER BY amount_minor_units DESC
            """,
            (period,),
        )
        return [
            {
                "source_node": str(r[0]),
                "target_node": str(r[1]),
                "amount_minor_units": int(r[2]),
            }
            for r in cursor.fetchall()
        ]
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query v_sankey_cash_flows view: {exc}",
        )
    finally:
        conn.close()


@router.get("/portfolio")
def get_portfolio_data(
    conn: sqlite3.Connection = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve consolidated multi-asset holdings, rational valuations, and unrealized P&L."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT commodity, total_units, total_cost_basis_minor_units, 
                   base_currency, market_value_minor_units, unrealized_gain_minor_units 
            FROM v_portfolio_holdings
            ORDER BY market_value_minor_units DESC
            """
        )
        return [
            {
                "commodity": str(r[0]),
                "total_units": int(r[1]) if r[1] is not None else 0,
                "total_cost_basis_minor_units": int(r[2]) if r[2] is not None else 0,
                "base_currency": str(r[3]),
                "market_value_minor_units": int(r[4]) if r[4] is not None else 0,
                "unrealized_gain_minor_units": int(r[5]) if r[5] is not None else 0,
            }
            for r in cursor.fetchall()
        ]
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query v_portfolio_holdings view: {exc}",
        )
    finally:
        conn.close()
