from __future__ import annotations

import email
from email.message import EmailMessage
import pytest

from ironledger.ingest.formats.email_receipt_engine import (
    UnwrappedEmail,
    unwrap_forwarded_email,
    parse_email_receipt,
)


def test_unwrap_gmail_forward():
    raw_eml = (
        "From: User Relay <user@gmail.com>\n"
        "To: sigil-inbox@ironledger.local\n"
        "Subject: Fwd: Your Amazon.com order # 114-9876543-1234567\n"
        "Date: Wed, 30 Sep 2026 10:00:00 -0400\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "\n"
        "---------- Forwarded message ---------\n"
        "From: auto-confirm@amazon.com\n"
        "Date: Wed, Sep 30, 2026 at 9:55 AM\n"
        "Subject: Your Amazon.com order # 114-9876543-1234567\n"
        "To: user@gmail.com\n"
        "\n"
        "Order #114-9876543-1234567\n"
        "Item: Mechanical Keyboard\n"
        "Price: $120.00\n"
        "Item: Keycap Puller\n"
        "Price: $8.50\n"
        "Total: $128.50\n"
    )
    unwrapped = unwrap_forwarded_email(raw_eml)
    assert unwrapped.is_forwarded is True
    assert unwrapped.forwarder_account == "user@gmail.com"
    assert unwrapped.original_sender == "auto-confirm@amazon.com"
    assert "Your Amazon.com order" in unwrapped.original_subject
    assert unwrapped.original_date == "2026-09-30"


def test_unwrap_outlook_forward():
    raw_eml = (
        "From: Soren Hotmail <soren@hotmail.com>\n"
        "To: sigil-inbox@ironledger.local\n"
        "Subject: FW: Apple Receipt - Invoice 10928374\n"
        "Date: Wed, 30 Sep 2026 12:00:00 +0000\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "\n"
        "-----Original Message-----\n"
        "From: no_reply@email.apple.com\n"
        "Sent: Wednesday, September 30, 2026 11:45 AM\n"
        "To: soren@hotmail.com\n"
        "Subject: Apple Receipt - Invoice 10928374\n"
        "\n"
        "iCloud+ 2TB Storage Plan: $9.99\n"
        "Total: $9.99\n"
    )
    unwrapped = unwrap_forwarded_email(raw_eml)
    assert unwrapped.is_forwarded is True
    assert unwrapped.forwarder_account == "soren@hotmail.com"
    assert unwrapped.original_sender == "no_reply@email.apple.com"
    assert unwrapped.original_date == "2026-09-30"


def test_unwrap_apple_mail_forward():
    raw_eml = (
        "From: Soren iCloud <soren@icloud.com>\n"
        "To: sigil-inbox@ironledger.local\n"
        "Subject: Fwd: Uber Trip Receipt\n"
        "Date: Wed, 30 Sep 2026 14:00:00 -0400\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "\n"
        "Begin forwarded message:\n"
        "From: Uber Receipts <uber.us@uber.com>\n"
        "Date: September 30, 2026 at 1:30:00 PM EDT\n"
        "To: soren@icloud.com\n"
        "Subject: Your Wednesday morning trip with Uber\n"
        "\n"
        "Ride to Office: $24.50\n"
        "Total: $24.50\n"
    )
    unwrapped = unwrap_forwarded_email(raw_eml)
    assert unwrapped.is_forwarded is True
    assert unwrapped.forwarder_account == "soren@icloud.com"
    assert unwrapped.original_sender == "uber.us@uber.com"
    assert unwrapped.original_date == "2026-09-30"


def test_parse_email_receipt_amazon_full():
    raw_eml = (
        "From: User <user@gmail.com>\n"
        "To: sigil-inbox@ironledger.local\n"
        "Subject: Fwd: Amazon Order 114-1111111-2222222\n"
        "Date: Wed, 30 Sep 2026 10:00:00 -0400\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "\n"
        "---------- Forwarded message ---------\n"
        "From: auto-confirm@amazon.com\n"
        "Date: 2026-09-30\n"
        "Subject: Your Amazon Order 114-1111111-2222222\n"
        "To: user@gmail.com\n"
        "\n"
        "Order #114-1111111-2222222\n"
        "Item: Ergonomic Mouse Pad $15.00\n"
        "Item: USB Hub $25.00\n"
        "Subtotal: $40.00\n"
        "Tax: $3.20\n"
        "Total: $43.20\n"
    )
    receipt = parse_email_receipt(raw_eml)
    assert receipt.merchant == "Amazon"
    assert receipt.order_date == "2026-09-30"
    assert receipt.subtotal_minor_units == 4000
    assert receipt.tax_minor_units == 320
    assert receipt.total_minor_units == 4320
    assert len(receipt.lines) == 2
    assert receipt.lines[0].item_title == "Ergonomic Mouse Pad"
    assert receipt.lines[0].total_price_minor == 1500
    assert receipt.lines[1].item_title == "USB Hub"
    assert receipt.lines[1].total_price_minor == 2500


@pytest.mark.parametrize("body,subtotal,shipping,discount,total,count", [
    ("Item A 34.00\nItem B 224.00\nSUB-TOTAL = $258.00\nABT CREDIT - CODE = - $50.00\nSHIPPING : 0.00 (UPS Ground)\nTAX = $0.00\nTOTAL = $208.00", 25800, 0, 5000, 20800, 2),
    ("Subtotal of Items: $124.99\nShipping & Handling: $6.98\nShipping Savings: -$6.98\nTotal for this Order: $124.99", 12499, 698, 698, 12499, 1),
    ("Book $15.63\nCD $14.99\nElectronics $43.44\nSoftware $37.99\nSubtotal of Items: $112.05\nShipping & Handling: $9.14\nTotal for this Order: $121.19", 11205, 914, 0, 12119, 4),
])
def test_receipt_summary_rows_are_not_items(body, subtotal, shipping, discount, total, count):
    raw = "From: auto-confirm@amazon.com\nDate: Wed, 30 Sep 2026 10:00:00 -0400\nSubject: Order with details\n\n" + body
    order = parse_email_receipt(raw)
    assert order.merchant_order_ref == ""
    assert (order.subtotal_minor_units, order.shipping_minor_units, order.discount_minor_units, order.total_minor_units) == (subtotal, shipping, discount, total)
    assert len(order.lines) == count
    assert sum(line.total_price_minor for line in order.lines) == subtotal


@pytest.mark.parametrize("body", [
    "Item $10.00\nSubtotal: $10.00\nTotal: $20.00",
    "Item $10.00\nSubtotal: $20.00",
    "Item $10.00\nTax: -$2.00",
    "Refund - $10.00",
])
def test_receipt_inconsistent_amounts_fail_closed(body):
    raw = "From: auto-confirm@amazon.com\nDate: Wed, 30 Sep 2026 10:00:00 -0400\nSubject: Order #114-123\n\n" + body
    with pytest.raises(ValueError):
        parse_email_receipt(raw)
