"""Subscription and recurring expense intelligence engine for IronLedger.

Provides deterministic cadence analysis, price-jump anomaly detection, and
normalized monthly overhead calculations using exact integer minor units.
Enforces zero floating-point arithmetic.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
import sqlite3
from typing import Any, Dict, List, Optional

__all__ = [
    "calculate_normalized_monthly_minor",
    "project_next_billing_date",
    "get_recurring_subscriptions",
]


def calculate_normalized_monthly_minor(amount_minor: int, cadence: str) -> int:
    """Normalize subscription minor unit amounts to a monthly equivalent using integer arithmetic."""
    if amount_minor <= 0:
        return 0

    cadence_upper = cadence.upper()
    if cadence_upper == "WEEKLY":
        # 52 weeks / 12 months with integer half-up rounding
        return (amount_minor * 52 + 6) // 12
    elif cadence_upper == "BIWEEKLY":
        # 26 bi-weekly periods / 12 months
        return (amount_minor * 26 + 6) // 12
    elif cadence_upper == "MONTHLY":
        return amount_minor
    elif cadence_upper == "QUARTERLY":
        # 4 quarters / 12 months = 1/3
        return (amount_minor + 1) // 3
    elif cadence_upper == "ANNUAL":
        # 1 year / 12 months = 1/12
        return (amount_minor + 6) // 12
    else:
        return amount_minor


def _add_months(source_date: date, months: int) -> date:
    """Add a specified number of calendar months, clamping day of month to valid range."""
    total_months = source_date.month - 1 + months
    year = source_date.year + total_months // 12
    month = total_months % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, max_day)
    return date(year, month, day)


def project_next_billing_date(last_date_str: str, cadence: str) -> str:
    """Project the next expected billing date given the last charge date and cadence."""
    try:
        dt = date.fromisoformat(last_date_str)
    except ValueError:
        return last_date_str

    cadence_upper = cadence.upper()
    if cadence_upper == "WEEKLY":
        next_dt = dt + timedelta(days=7)
    elif cadence_upper == "BIWEEKLY":
        next_dt = dt + timedelta(days=14)
    elif cadence_upper == "MONTHLY":
        next_dt = _add_months(dt, 1)
    elif cadence_upper == "QUARTERLY":
        next_dt = _add_months(dt, 3)
    elif cadence_upper == "ANNUAL":
        next_dt = _add_months(dt, 12)
    else:
        next_dt = dt + timedelta(days=30)

    return next_dt.isoformat()


def get_recurring_subscriptions(
    conn: sqlite3.Connection,
    ledger_id: str = "default",
    cadence_filter: Optional[str] = None,
    include_irregular: bool = False,
) -> Dict[str, Any]:
    """Query recurring subscriptions, calculate normalized monthly cost and detect price jumps."""
    clauses = ["ledger_id = ?"]
    params: List[Any] = [ledger_id]

    if cadence_filter is not None:
        clauses.append("cadence = ?")
        params.append(cadence_filter.upper())
    elif not include_irregular:
        clauses.append("cadence != 'IRREGULAR'")

    where_clause = " AND ".join(clauses)

    query = f"""
        SELECT
            ledger_id,
            account,
            normalized_payee,
            display_payee,
            currency,
            minor_unit_scale,
            occurrence_count,
            first_date,
            last_date,
            avg_interval_days,
            last_amount_minor,
            prev_amount_minor,
            cadence,
            is_price_jump,
            price_jump_minor
        FROM v_recurring_subscriptions
        WHERE {where_clause}
        ORDER BY last_amount_minor DESC, display_payee ASC
    """

    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()

    subscriptions: List[Dict[str, Any]] = []
    price_jumps: List[Dict[str, Any]] = []
    total_monthly_overhead_minor = 0

    for row in rows:
        (
            lid,
            acct,
            norm_payee,
            disp_payee,
            curr,
            scale,
            occurrences,
            first_dt,
            last_dt,
            interval_days,
            last_amt,
            prev_amt,
            cadence,
            is_jump,
            jump_amt,
        ) = row

        normalized_monthly = calculate_normalized_monthly_minor(int(last_amt), str(cadence))
        next_billing = project_next_billing_date(str(last_dt), str(cadence))
        total_monthly_overhead_minor += normalized_monthly

        item: Dict[str, Any] = {
            "ledger_id": str(lid),
            "account": str(acct),
            "normalized_payee": str(norm_payee),
            "display_payee": str(disp_payee),
            "currency": str(curr),
            "minor_unit_scale": int(scale),
            "occurrence_count": int(occurrences),
            "first_date": str(first_dt),
            "last_date": str(last_dt),
            "avg_interval_days": int(interval_days) if interval_days is not None else 0,
            "last_amount_minor": int(last_amt),
            "prev_amount_minor": int(prev_amt),
            "cadence": str(cadence),
            "is_price_jump": bool(is_jump),
            "price_jump_minor": int(jump_amt),
            "projected_next_date": next_billing,
            "normalized_monthly_minor": normalized_monthly,
        }

        subscriptions.append(item)
        if is_jump:
            price_jumps.append(item)

    return {
        "ledger_id": ledger_id,
        "subscription_count": len(subscriptions),
        "price_jump_count": len(price_jumps),
        "total_monthly_overhead_minor": total_monthly_overhead_minor,
        "subscriptions": subscriptions,
        "price_jumps": price_jumps,
    }
