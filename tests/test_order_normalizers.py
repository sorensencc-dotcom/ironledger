from __future__ import annotations

import io
import pytest

from ironledger.ingest.formats.amazon_order_normalizer import (
    parse_amazon_orders_csv,
    parse_currency_to_minor_units,
)
from ironledger.ingest.formats.venmo_normalizer import parse_venmo_statement_csv


def test_parse_currency_to_minor_units():
    assert parse_currency_to_minor_units("$10.50") == 1050
    assert parse_currency_to_minor_units("10.50") == 1050
    assert parse_currency_to_minor_units("-$10.50") == -1050
    assert parse_currency_to_minor_units("($10.50)") == -1050
    assert parse_currency_to_minor_units("$1,234.56") == 123456
    assert parse_currency_to_minor_units("$0.00") == 0
    assert parse_currency_to_minor_units("5") == 500

    with pytest.raises(Exception):
        parse_currency_to_minor_units("$10.555")  # Fractional cents beyond scale 2


def test_amazon_order_normalizer_single_and_multi_line():
    csv_content = (
        "Order Date,Order ID,Title,Quantity,Item Subtotal,Item Subtotal Tax,Shipping & Handling Charge,Total Amount\n"
        "2026-09-29,112-1234567-8901234,Clean Code Book,1,$30.00,$2.50,$0.00,$32.50\n"
        "2026-09-29,112-1234567-8901234,USB-C Cable 2-Pack,2,$20.00,$1.60,$0.00,$21.60\n"
        "2026-09-28,112-9999999-0000000,Coffee Beans 2lb,1,$25.00,$0.00,$5.00,$30.00\n"
    )
    orders = parse_amazon_orders_csv(csv_content)
    assert len(orders) == 2

    # First order with 2 item lines
    ord1 = [o for o in orders if o.merchant_order_ref == "112-1234567-8901234"][0]
    assert ord1.merchant == "Amazon"
    assert ord1.order_date == "2026-09-29"
    assert ord1.currency == "USD"
    assert ord1.subtotal_minor_units == 5000
    assert ord1.tax_minor_units == 410
    assert ord1.shipping_minor_units == 0
    assert ord1.total_minor_units == 5410
    assert len(ord1.lines) == 2
    assert ord1.lines[0].item_title == "Clean Code Book"
    assert ord1.lines[0].total_price_minor == 3000
    assert ord1.lines[1].item_title == "USB-C Cable 2-Pack"
    assert ord1.lines[1].total_price_minor == 2000

    # Second order
    ord2 = [o for o in orders if o.merchant_order_ref == "112-9999999-0000000"][0]
    assert ord2.subtotal_minor_units == 2500
    assert ord2.shipping_minor_units == 500
    assert ord2.total_minor_units == 3000
    assert len(ord2.lines) == 1


def test_venmo_normalizer():
    csv_content = (
        "ID,Datetime,Type,Status,Note,From,To,Amount (total)\n"
        "392019481,2026-09-29T14:30:00,Payment,Complete,Dinner at Gusto,Alice,Bob,-$45.00\n"
        "392019482,2026-09-29T15:00:00,Payment,Complete,Uber split,Charlie,Bob,-$18.50\n"
    )
    orders = parse_venmo_statement_csv(csv_content)
    assert len(orders) == 2
    assert orders[0].merchant == "Venmo"
    assert orders[0].merchant_order_ref == "392019481"
    assert orders[0].order_date == "2026-09-29"
    assert orders[0].total_minor_units == 4500
    assert len(orders[0].lines) == 1
    assert orders[0].lines[0].item_title == "Dinner at Gusto"
    assert orders[0].lines[0].total_price_minor == 4500
