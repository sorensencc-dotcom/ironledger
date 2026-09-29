"""Amazon Order History CSV Normalizer.

Parses Amazon Order History reports and returns structured ParsedItemizedOrder records
with zero-float minor unit arithmetic.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime

from ironledger.ingest.errors import ParseError
from ironledger.ingest.formats.csv_engine import parse_amount_to_text


def parse_currency_to_minor_units(val: str, scale: int = 2) -> int:
    """Parse money text to integer minor units without float operations."""
    normalized = parse_amount_to_text(val)
    negative = normalized.startswith("-")
    if negative:
        normalized = normalized[1:]
    if "." in normalized:
        parts = normalized.split(".")
        if len(parts) != 2:
            raise ParseError(f"Invalid decimal string: {val!r}")
        whole_str, frac_str = parts
        if len(frac_str) > scale:
            raise ParseError(f"Precision beyond scale {scale}: {val!r}")
        frac_str = frac_str.ljust(scale, "0")
    else:
        whole_str = normalized
        frac_str = "0" * scale
    cents = int(whole_str) * (10 ** scale) + int(frac_str)
    return -cents if negative else cents


@dataclass(frozen=True)
class ParsedOrderLine:
    line_index: int
    item_title: str
    item_description: str
    quantity: int
    unit_price_minor: int | None
    total_price_minor: int
    proposed_account: str
    confidence_score: int


@dataclass(frozen=True)
class ParsedItemizedOrder:
    order_id: str
    merchant: str
    merchant_order_ref: str
    order_date: str
    currency: str
    subtotal_minor_units: int
    tax_minor_units: int
    shipping_minor_units: int
    discount_minor_units: int
    total_minor_units: int
    lines: tuple[ParsedOrderLine, ...]


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_").replace("&", "and")


def parse_amazon_orders_csv(content: str) -> list[ParsedItemizedOrder]:
    """Parse an Amazon Order History CSV into a list of itemized orders."""
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

    # Group rows by order ID
    order_groups: dict[str, list[list[str]]] = {}
    for row in rows[1:]:
        if not row or not any(row):
            continue
        order_ref = get_col(row, "order_id", "order_identification", "order_number")
        if not order_ref:
            order_ref = f"row_{len(order_groups)}"
        order_groups.setdefault(order_ref, []).append(row)

    itemized_orders: list[ParsedItemizedOrder] = []

    for order_ref, group_rows in order_groups.items():
        first_row = group_rows[0]
        raw_date = get_col(first_row, "order_date", "date")
        try:
            # support YYYY-MM-DD or MM/DD/YYYY
            if "/" in raw_date:
                dt = datetime.strptime(raw_date, "%m/%d/%Y")
            else:
                dt = datetime.strptime(raw_date[:10], "%Y-%m-%d")
            order_date = dt.strftime("%Y-%m-%d")
        except Exception:
            order_date = raw_date[:10] if len(raw_date) >= 10 else "1970-01-01"

        currency = get_col(first_row, "currency", "currency_code") or "USD"
        order_id = "ord_" + hashlib.sha256(f"Amazon:{order_ref}:{order_date}".encode("utf-8")).hexdigest()[:16]

        lines: list[ParsedOrderLine] = []
        subtotal_minor = 0
        tax_minor = 0
        shipping_minor = 0
        discount_minor = 0

        for line_idx, row in enumerate(group_rows):
            title = get_col(row, "title", "item_name", "product_name", "item_title") or "Amazon Item"
            category = get_col(row, "category", "item_category")
            qty_str = get_col(row, "quantity", "qty") or "1"
            try:
                quantity = max(1, int(qty_str))
            except ValueError:
                quantity = 1

            subtotal_str = get_col(row, "item_subtotal", "unit_price", "price", "item_total")
            row_subtotal = parse_currency_to_minor_units(subtotal_str) if subtotal_str else 0
            subtotal_minor += row_subtotal

            tax_str = get_col(row, "item_subtotal_tax", "tax", "item_tax")
            if tax_str:
                tax_minor += parse_currency_to_minor_units(tax_str)

            shipping_str = get_col(row, "shipping_and_handling_charge", "shipping", "shipping_charge")
            if shipping_str:
                shipping_minor += parse_currency_to_minor_units(shipping_str)

            discount_str = get_col(row, "promotion_discount", "discount", "promotional_discount")
            if discount_str:
                discount_minor += abs(parse_currency_to_minor_units(discount_str))

            unit_price = row_subtotal // quantity if quantity > 0 else row_subtotal

            lines.append(
                ParsedOrderLine(
                    line_index=line_idx,
                    item_title=title,
                    item_description=f"Category: {category}" if category else "",
                    quantity=quantity,
                    unit_price_minor=unit_price,
                    total_price_minor=row_subtotal,
                    proposed_account="Expenses:Uncategorized",
                    confidence_score=50,
                )
            )

        total_minor = subtotal_minor + tax_minor + shipping_minor - discount_minor

        itemized_orders.append(
            ParsedItemizedOrder(
                order_id=order_id,
                merchant="Amazon",
                merchant_order_ref=order_ref,
                order_date=order_date,
                currency=currency,
                subtotal_minor_units=subtotal_minor,
                tax_minor_units=tax_minor,
                shipping_minor_units=shipping_minor,
                discount_minor_units=discount_minor,
                total_minor_units=total_minor,
                lines=tuple(lines),
            )
        )

    return itemized_orders
