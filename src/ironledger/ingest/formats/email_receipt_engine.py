"""Email Receipt Ingestion Engine & Multi-Account Forward Unwrapper.

Unwraps forwarded RFC 822 emails (.eml) from Gmail, Outlook/Hotmail, Apple Mail/iCloud,
extracting the original merchant, date, items, and amounts with zero-float integer arithmetic.
"""

from __future__ import annotations

import email
from email.header import decode_header, make_header
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

from ironledger.ingest.formats.amazon_order_normalizer import (
    ParsedItemizedOrder,
    ParsedOrderLine,
    parse_currency_to_minor_units,
)


@dataclass(frozen=True)
class UnwrappedEmail:
    is_forwarded: bool
    forwarder_account: str
    original_sender: str
    original_date: str
    original_subject: str
    body_text: str
    raw_headers: dict[str, str]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result: list[str] = []

    def handle_data(self, d):
        self.result.append(d)

    def get_text(self) -> str:
        return " ".join(self.result)


def _decode_header_str(val: str | None) -> str:
    if not val:
        return ""
    try:
        return str(make_header(decode_header(val)))
    except Exception:
        return val


def _extract_email_address(raw: str) -> str:
    match = re.search(r"[\w\.-]+@[\w\.-]+", raw)
    return match.group(0) if match else raw.strip()


def _extract_body(msg: email.message.Message) -> str:
    texts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition", ""))
            if "attachment" in cdisp:
                continue
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    texts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
            elif ctype == "text/html" and not texts:
                payload = part.get_payload(decode=True)
                if payload:
                    html_str = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    parser = _HTMLTextExtractor()
                    parser.feed(html_str)
                    texts.append(parser.get_text())
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            texts.append(payload.decode(charset, errors="replace"))
    return "\n".join(texts)


def _parse_date_to_iso(raw_date: str) -> str:
    clean_date = raw_date.strip()
    # Match YYYY-MM-DD directly
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", clean_date)
    if iso_match:
        return iso_match.group(1)

    # Clean date string
    normalized_date = re.sub(r"\s+\([A-Z]+\)$", "", clean_date)
    normalized_date = re.sub(r"\s+[A-Z]{3,4}$", "", normalized_date)  # strip EDT/EST/PST/UTC

    # Common email date formats
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z",
        "%a, %b %d, %Y at %I:%M %p",
        "%a, %b %d, %Y at %I:%M:%S %p",
        "%A, %B %d, %Y %I:%M %p",
        "%B %d, %Y at %I:%M:%S %p",
        "%B %d, %Y at %I:%M %p",
        "%B %d, %Y",
        "%b %d, %Y",
    ):
        try:
            dt = datetime.strptime(normalized_date.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Fallback to today or safe 1970 date
    return datetime.now().strftime("%Y-%m-%d")


def unwrap_forwarded_email(raw_eml: str | bytes) -> UnwrappedEmail:
    """Unwrap a potentially forwarded RFC 822 email message."""
    if isinstance(raw_eml, str):
        msg = email.message_from_string(raw_eml)
    else:
        msg = email.message_from_bytes(raw_eml)

    envelope_from = _extract_email_address(_decode_header_str(msg.get("From", "")))
    envelope_subject = _decode_header_str(msg.get("Subject", ""))
    envelope_date = _decode_header_str(msg.get("Date", ""))

    raw_body = _extract_body(msg)

    # Check Resent-From headers
    resent_from = msg.get("Resent-From")
    if resent_from:
        return UnwrappedEmail(
            is_forwarded=True,
            forwarder_account=_extract_email_address(_decode_header_str(resent_from)),
            original_sender=envelope_from,
            original_date=_parse_date_to_iso(envelope_date),
            original_subject=envelope_subject,
            body_text=raw_body,
            raw_headers=dict(msg.items()),
        )

    # Patterns for forwarded headers embedded in body text
    forward_markers = [
        r"-+\s*Forwarded message\s*-+",
        r"-+\s*Original Message\s*-+",
        r"Begin forwarded message:",
    ]

    for marker in forward_markers:
        split_parts = re.split(marker, raw_body, maxsplit=1, flags=re.IGNORECASE)
        if len(split_parts) == 2:
            inner_block = split_parts[1]
            header_lines = inner_block.splitlines()[:15]
            orig_sender = ""
            orig_date = ""
            orig_subject = ""
            for line in header_lines:
                line_str = line.strip()
                if re.match(r"^From:\s*", line_str, re.IGNORECASE):
                    orig_sender = _extract_email_address(re.sub(r"^From:\s*", "", line_str, flags=re.IGNORECASE))
                elif re.match(r"^(?:Date|Sent):\s*", line_str, re.IGNORECASE):
                    orig_date = re.sub(r"^(?:Date|Sent):\s*", "", line_str, flags=re.IGNORECASE)
                elif re.match(r"^Subject:\s*", line_str, re.IGNORECASE):
                    orig_subject = re.sub(r"^Subject:\s*", "", line_str, flags=re.IGNORECASE)

            if orig_sender:
                return UnwrappedEmail(
                    is_forwarded=True,
                    forwarder_account=envelope_from,
                    original_sender=orig_sender,
                    original_date=_parse_date_to_iso(orig_date) if orig_date else _parse_date_to_iso(envelope_date),
                    original_subject=orig_subject or envelope_subject,
                    body_text=inner_block,
                    raw_headers=dict(msg.items()),
                )

    # Direct email
    return UnwrappedEmail(
        is_forwarded=False,
        forwarder_account=envelope_from,
        original_sender=envelope_from,
        original_date=_parse_date_to_iso(envelope_date),
        original_subject=envelope_subject,
        body_text=raw_body,
        raw_headers=dict(msg.items()),
    )


def _detect_merchant(sender: str, subject: str) -> str:
    combined = f"{sender} {subject}".lower()
    if "amazon" in combined:
        return "Amazon"
    if "apple" in combined or "itunes" in combined:
        return "Apple"
    if "uber" in combined:
        return "Uber"
    if "lyft" in combined:
        return "Lyft"
    if "doordash" in combined:
        return "DoorDash"
    if "instacart" in combined:
        return "Instacart"
    if "target" in combined:
        return "Target"
    if "walmart" in combined:
        return "Walmart"
    # fallback to domain name
    if "@" in sender:
        domain = sender.split("@")[-1].split(".")[0]
        return domain.capitalize()
    return "Unknown Merchant"


def parse_email_receipt(raw_eml: str | bytes) -> ParsedItemizedOrder:
    """Parse an email receipt (.eml) into a ParsedItemizedOrder."""
    unwrapped = unwrap_forwarded_email(raw_eml)
    merchant = _detect_merchant(unwrapped.original_sender, unwrapped.original_subject)

    # Extract order reference from subject or body
    order_ref_match = re.search(r"(?:order|invoice|trip)\s*(?:#|number|id)?\s*([0-9a-zA-Z-]+)", f"{unwrapped.original_subject}\n{unwrapped.body_text}", re.IGNORECASE)
    merchant_order_ref = order_ref_match.group(1) if order_ref_match else ""

    body = unwrapped.body_text
    lines: list[ParsedOrderLine] = []
    subtotal_minor = 0
    tax_minor = 0
    shipping_minor = 0
    discount_minor = 0
    total_minor = 0

    # Line item regex: e.g. "Item: Mechanical Keyboard Price: $120.00" or "Ergonomic Mouse Pad $15.00"
    for line in body.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        # Look for explicit subtotal / tax / shipping / total lines
        if re.match(r"^Subtotal:\s*", line_clean, re.IGNORECASE):
            amt_match = re.search(r"(\$?[0-9,]+\.[0-9]{2})", line_clean)
            if amt_match:
                subtotal_minor = parse_currency_to_minor_units(amt_match.group(1))
            continue

        if re.match(r"^Tax:\s*", line_clean, re.IGNORECASE):
            amt_match = re.search(r"(\$?[0-9,]+\.[0-9]{2})", line_clean)
            if amt_match:
                tax_minor = parse_currency_to_minor_units(amt_match.group(1))
            continue

        if re.match(r"^(?:Shipping|Delivery):\s*", line_clean, re.IGNORECASE):
            amt_match = re.search(r"(\$?[0-9,]+\.[0-9]{2})", line_clean)
            if amt_match:
                shipping_minor = parse_currency_to_minor_units(amt_match.group(1))
            continue

        if re.match(r"^Total:\s*", line_clean, re.IGNORECASE):
            amt_match = re.search(r"(\$?[0-9,]+\.[0-9]{2})", line_clean)
            if amt_match:
                total_minor = parse_currency_to_minor_units(amt_match.group(1))
            continue

        # Regular item line: "Item: <Title> Price: <Price>" or "<Title>: <Price>" or "<Title> <Price>"
        item_match = re.search(r"^(?:Item:\s*)?(.*?)(?::\s*|\s+)(\$?[0-9,]+\.[0-9]{2})$", line_clean, re.IGNORECASE)
        if item_match:
            title = item_match.group(1).strip()
            price_str = item_match.group(2).strip()
            # Ignore headers like Subtotal / Tax that matched general format
            if title.lower() in ("subtotal", "tax", "shipping", "total", "discount"):
                continue
            if title:
                item_price = parse_currency_to_minor_units(price_str)
                lines.append(
                    ParsedOrderLine(
                        line_index=len(lines),
                        item_title=title,
                        item_description=f"Source: {unwrapped.forwarder_account}",
                        quantity=1,
                        unit_price_minor=item_price,
                        total_price_minor=item_price,
                        proposed_account="Expenses:Uncategorized",
                        confidence_score=75,
                    )
                )

    if lines:
        subtotal_minor = sum(l.total_price_minor for l in lines)
        total_minor = subtotal_minor + tax_minor + shipping_minor - discount_minor
    else:
        if total_minor:
            subtotal_minor = total_minor - tax_minor - shipping_minor + discount_minor
        else:
            total_minor = subtotal_minor + tax_minor + shipping_minor - discount_minor

        if subtotal_minor > 0 or total_minor > 0:
            line_amt = subtotal_minor if subtotal_minor > 0 else total_minor
            lines.append(
                ParsedOrderLine(
                    line_index=0,
                    item_title=unwrapped.original_subject or f"{merchant} Purchase",
                    item_description=f"Source: {unwrapped.forwarder_account}",
                    quantity=1,
                    unit_price_minor=line_amt,
                    total_price_minor=line_amt,
                    proposed_account="Expenses:Uncategorized",
                    confidence_score=50,
                )
            )

    order_id = "ord_" + hashlib.sha256(f"{merchant}:{merchant_order_ref}:{unwrapped.original_date}:{total_minor}".encode("utf-8")).hexdigest()[:16]

    return ParsedItemizedOrder(
        order_id=order_id,
        merchant=merchant,
        merchant_order_ref=merchant_order_ref,
        order_date=unwrapped.original_date,
        currency="USD",
        subtotal_minor_units=subtotal_minor,
        tax_minor_units=tax_minor,
        shipping_minor_units=shipping_minor,
        discount_minor_units=discount_minor,
        total_minor_units=total_minor,
        lines=tuple(lines),
    )
