"""Venmo Statement CSV Normalizer.

Parses Venmo transaction histories into ParsedItemizedOrder records
with zero-float minor unit arithmetic.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime

from ironledger.ingest.formats.amazon_order_normalizer import (
    ParsedItemizedOrder,
    ParsedOrderLine,
    parse_currency_to_minor_units,
)


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_").replace("(", "").replace(")", "")


def parse_venmo_statement_csv(content: str) -> list[ParsedItemizedOrder]:
    """Parse a Venmo statement CSV into a list of itemized orders."""
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return []

    raw_headers = rows[0]
    header_map = {_normalize_header(h): idx for idx, h in enumerate(raw_headers)}

    def get_col(row: list[str], *candidates: str) -> str:
        for c in candidates:
            idx = header_map.get(c)
            if idx is not None and idx < len(row):
                val = row[idx].strip()
                if val:
                    return val
        return ""

    orders: list[ParsedItemizedOrder] = []

    for row_idx, row in enumerate(rows[1:]):
        if not row or not any(row):
            continue
        order_ref = get_col(row, "id", "transaction_id") or f"venmo_row_{row_idx}"
        raw_dt = get_col(row, "datetime", "date")
        try:
            order_date = raw_dt[:10] if raw_dt else "1970-01-01"
            datetime.strptime(order_date, "%Y-%m-%d")
        except Exception:
            order_date = "1970-01-01"

        note = get_col(row, "note", "description") or "Venmo Payment"
        from_user = get_col(row, "from", "sender")
        to_user = get_col(row, "to", "recipient")
        party_info = f"From: {from_user}, To: {to_user}" if (from_user or to_user) else ""

        amt_str = get_col(row, "amount_total", "amount")
        if not amt_str:
            continue
        amt_minor = abs(parse_currency_to_minor_units(amt_str))

        order_id = "ord_" + hashlib.sha256(f"Venmo:{order_ref}:{order_date}".encode("utf-8")).hexdigest()[:16]

        line = ParsedOrderLine(
            line_index=0,
            item_title=note,
            item_description=party_info,
            quantity=1,
            unit_price_minor=amt_minor,
            total_price_minor=amt_minor,
            proposed_account="Expenses:Uncategorized",
            confidence_score=50,
        )

        orders.append(
            ParsedItemizedOrder(
                order_id=order_id,
                merchant="Venmo",
                merchant_order_ref=order_ref,
                order_date=order_date,
                currency="USD",
                subtotal_minor_units=amt_minor,
                tax_minor_units=0,
                shipping_minor_units=0,
                discount_minor_units=0,
                total_minor_units=amt_minor,
                lines=(line,),
            )
        )

    return orders
