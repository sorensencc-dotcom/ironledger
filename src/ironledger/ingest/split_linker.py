"""Multi-Leg Split Linker & 3-Tier Itemized Categorization Engine.

Links itemized e-commerce orders (Amazon, Venmo, email receipts) to staged parent transactions,
generating multi-leg contra posting proposals with integer zero-float precision.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from ironledger.audit import append_audit_event
from ironledger.conventions import (
    ConventionError,
    validate_account_name,
    validate_same_currency_balance,
)
from ironledger.ingest.formats.amazon_order_normalizer import (
    ParsedItemizedOrder,
    ParsedOrderLine,
)
from ironledger.ingest.identity import canonical_payee
from ironledger.review.rules import resolve_rule_row

# Built-in keyword taxonomy heuristic for Tier 2 item categorization
KEYWORD_TAXONOMY: list[tuple[tuple[str, ...], str]] = [
    (
        ("book", "books", "cookbook", "kindle", "audiobook", "paperback", "hardcover", "textbook", "novel", "author", "guide", "manual"),
        "Expenses:Books",
    ),
    (
        ("keyboard", "mouse", "cable", "usb", "adapter", "charger", "monitor", "electronics", "hardware", "laptop", "headphone", "airpods", "ipad", "iphone", "gpu", "cpu", "ssd", "ram", "drive"),
        "Expenses:Electronics",
    ),
    (
        ("groceries", "coffee", "tea", "snack", "food", "dinner", "lunch", "breakfast", "pizza", "restaurant", "cafe", "bakery", "produce", "meat", "beverage", "soda", "wine", "beer"),
        "Expenses:Food",
    ),
    (
        ("cleaning", "detergent", "soap", "paper towel", "toilet paper", "household", "furniture", "kitchen", "bath", "bedding", "towel", "trash bag", "sponge", "cleaner"),
        "Expenses:Household",
    ),
    (
        ("uber", "lyft", "transport", "transit", "taxi", "subway", "train", "flight", "airline", "parking", "toll", "gas", "fuel", "metro"),
        "Expenses:Transport",
    ),
    (
        ("software", "subscription", "icloud", "github", "openai", "aws", "digitalocean", "domain", "hosting", "saas", "app store", "google play", "license", "copilot"),
        "Expenses:Software",
    ),
]

_TAXONOMY_CACHE: tuple[float, list[tuple[tuple[str, ...], str]]] | None = None


def load_keyword_taxonomy(path: str | Path | None = None) -> list[tuple[tuple[str, ...], str]]:
    """Load taxonomy JSON when changed; retain built-in rules if file is absent."""
    global _TAXONOMY_CACHE
    taxonomy_path = Path(path) if path is not None else Path(__file__).parents[3] / "config" / "taxonomy.json"
    try:
        mtime = taxonomy_path.stat().st_mtime
    except FileNotFoundError:
        return KEYWORD_TAXONOMY
    if _TAXONOMY_CACHE is not None and _TAXONOMY_CACHE[0] == mtime:
        return _TAXONOMY_CACHE[1]
    raw = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    loaded: list[tuple[tuple[str, ...], str]] = []
    for entry in raw.get("categories", []):
        keywords = tuple(str(keyword).strip().lower() for keyword in entry.get("keywords", []) if str(keyword).strip())
        account = str(entry.get("account", "")).strip()
        if keywords and account:
            validate_account_name(account)
            loaded.append((keywords, account))
    if not loaded:
        raise ValueError(f"Taxonomy file has no valid categories: {taxonomy_path}")
    _TAXONOMY_CACHE = (mtime, loaded)
    return loaded


def find_shipment_match(
    line_amounts: list[int] | tuple[int, ...],
    charge_minor: int,
    tax_minor: int = 0,
    shipping_minor: int = 0,
    discount_minor: int = 0,
) -> dict[str, object] | None:
    """Find deterministic line subset matching a partial shipment charge using integer math."""
    subtotal = sum(line_amounts)
    target = abs(charge_minor)
    if subtotal <= 0 or target <= 0:
        return None
    sums: dict[int, tuple[int, ...]] = {0: ()}
    for index, amount in enumerate(line_amounts):
        if amount <= 0:
            continue
        for current, indices in list(sums.items()):
            candidate = current + amount
            if candidate not in sums:
                sums[candidate] = indices + (index,)
    for line_total, indices in sorted(sums.items(), key=lambda item: (len(item[1]), item[1])):
        if not indices:
            continue
        allocated_tax = tax_minor * line_total // subtotal
        allocated_shipping = shipping_minor * line_total // subtotal
        allocated_discount = discount_minor * line_total // subtotal
        if line_total + allocated_tax + allocated_shipping - allocated_discount == target:
            return {
                "line_indices": indices,
                "line_total_minor": line_total,
                "tax_minor": allocated_tax,
                "shipping_minor": allocated_shipping,
                "discount_minor": allocated_discount,
            }
    return None

def categorize_order_line(
    conn: sqlite3.Connection,
    item_title: str,
    item_desc: str = "",
    merchant: str = "",
    ledger_id: str = "default",
    now_utc: str | None = None,
    taxonomy_path: str | Path | None = None,
) -> tuple[str, int]:
    """Categorize an order line item through 3 tiers.

    Returns (proposed_account, confidence_score).
    """
    clean_title = item_title.strip()

    # Tier 1: Deterministic Review Rules (95% confidence)
    try:
        hit = resolve_rule_row(conn, canonical_payee(clean_title), importing_account=None, now_utc=now_utc)
        if hit is not None:
            _rule_id, target_account = hit
            return target_account, 95
    except Exception:
        pass

    # Tier 2: Keyword Taxonomy Heuristic (80-85% confidence)
    text_to_search = f"{clean_title} {item_desc} {merchant}".lower()
    for keywords, account in load_keyword_taxonomy(taxonomy_path):
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text_to_search) or kw in text_to_search:
                return account, 85

    # Tier 3: Uncategorized fallback (50% confidence)
    return "Expenses:Uncategorized", 50


def propose_splits_for_order(
    conn: sqlite3.Connection,
    order: ParsedItemizedOrder,
    source_document_id: str,
    ledger_id: str = "default",
    now_utc: str | None = None,
) -> str | None:
    """Store an itemized order, categorize its lines, and propose splits for candidate staged transactions."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Insert itemized_order
    conn.execute(
        "INSERT INTO itemized_orders ("
        "  order_id, source_document_id, ledger_id, merchant, merchant_order_ref, "
        "  order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, "
        "  discount_minor_units, total_minor_units, created_at_utc"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (order_id) DO NOTHING",
        (
            order.order_id,
            source_document_id,
            ledger_id,
            order.merchant,
            order.merchant_order_ref,
            order.order_date,
            order.currency,
            order.subtotal_minor_units,
            order.tax_minor_units,
            order.shipping_minor_units,
            order.discount_minor_units,
            order.total_minor_units,
            now_utc,
        ),
    )

    # Insert categorized lines
    for line in order.lines:
        line_id = f"line_{order.order_id}_{line.line_index}"
        if line.proposed_account and line.proposed_account != "Expenses:Uncategorized":
            account = line.proposed_account
            confidence = line.confidence_score
        else:
            account, confidence = categorize_order_line(
                conn, line.item_title, line.item_description, order.merchant, ledger_id, now_utc
            )
        conn.execute(
            "INSERT INTO itemized_order_lines ("
            "  line_id, order_id, line_index, item_title, item_description, "
            "  quantity, unit_price_minor, total_price_minor, proposed_account, confidence_score, created_at_utc"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (order_id, line_index) DO NOTHING",
            (
                line_id,
                order.order_id,
                line.line_index,
                line.item_title,
                line.item_description,
                line.quantity,
                line.unit_price_minor,
                line.total_price_minor,
                account,
                confidence,
                now_utc,
            ),
        )

    # Match full orders and partial shipment charges against pending imported postings.
    candidates = conn.execute(
        "SELECT st.staged_transaction_id, st.proposed_date, st.payee, sp.minor_units, sp.currency "
        "FROM staged_transactions st "
        "JOIN staged_postings sp ON st.staged_transaction_id = sp.staged_transaction_id AND sp.role = 'imported' "
        "WHERE st.ledger_id = ? AND st.status = 'pending' AND sp.currency = ?",
        (ledger_id, order.currency),
    ).fetchall()

    created_proposal_id: str | None = None

    for cand_stx_id, cand_date, cand_payee, cand_minor, _cand_curr in candidates:
        shipment = None
        if abs(cand_minor) != order.total_minor_units:
            shipment = find_shipment_match(
                [line.total_price_minor for line in order.lines],
                cand_minor,
                tax_minor=order.tax_minor_units,
                shipping_minor=order.shipping_minor_units,
                discount_minor=order.discount_minor_units,
            )
            if shipment is None:
                continue
        # Compute match confidence
        match_conf = 80
        merchant_norm = order.merchant.lower()
        payee_norm = (cand_payee or "").lower()

        if merchant_norm in payee_norm or payee_norm in merchant_norm or "amzn" in payee_norm or "amazon" in payee_norm:
            match_conf += 10
        if cand_date == order.order_date:
            match_conf += 8

        match_conf = min(100, match_conf)
        proposal_id = f"prop_{order.order_id}_{cand_stx_id}"

        conn.execute(
            "INSERT INTO split_proposals ("
            "  proposal_id, order_id, target_type, target_id, parent_amount_minor, match_confidence, status, created_at_utc, "
            "  selected_line_indices, allocated_tax_minor, allocated_shipping_minor, allocated_discount_minor"
            ") VALUES (?, ?, 'staged_transaction', ?, ?, ?, 'pending', ?, ?, ?, ?, ?) "
            "ON CONFLICT (order_id, target_type, target_id) DO NOTHING",
            (
                proposal_id,
                order.order_id,
                cand_stx_id,
                cand_minor,
                match_conf,
                now_utc,
                json.dumps(shipment["line_indices"]) if shipment else None,
                shipment["tax_minor"] if shipment else None,
                shipment["shipping_minor"] if shipment else None,
                shipment["discount_minor"] if shipment else None,
            ),
        )
        created_proposal_id = proposal_id

    conn.commit()
    return created_proposal_id


def apply_staged_transaction_split(
    conn: sqlite3.Connection,
    stx_id: str,
    contra_postings: list[dict],
    now_utc: str | None = None,
    source_record_id: str | None = None,
) -> None:
    """Replace contra postings for a staged transaction with validated balanced split postings."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    imported_row = conn.execute(
        "SELECT source_record_id, account, minor_units, currency, minor_unit_scale, ledger_id "
        "FROM staged_postings WHERE staged_transaction_id = ? AND role = 'imported'",
        (stx_id,),
    ).fetchone()
    if not imported_row:
        raise ValueError(f"Staged transaction {stx_id} has no imported posting")

    srec_id, imp_acc, imp_units, imp_curr, imp_scale, ledger_id = imported_row
    effective_srec = source_record_id or srec_id

    # Verify balance
    all_postings_dict = [
        {
            "account": imp_acc,
            "currency": imp_curr,
            "minor_units": imp_units,
            "scale": imp_scale,
        }
    ]
    for p in contra_postings:
        all_postings_dict.append(
            {
                "account": p["account"],
                "currency": p.get("currency", imp_curr),
                "minor_units": p["minor_units"],
                "scale": p.get("scale", imp_scale),
            }
        )

    validate_same_currency_balance(all_postings_dict)

    # Delete existing contra postings
    conn.execute(
        "DELETE FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
        (stx_id,),
    )

    # Insert new contra postings
    for idx, p in enumerate(contra_postings, start=1):
        posting_id = f"spst_{uuid.uuid4().hex[:12]}"
        account = p["account"]
        validate_account_name(account)
        conn.execute(
            "INSERT INTO staged_postings ("
            "  staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, "
            "  account, minor_units, currency, minor_unit_scale, created_at_utc, ledger_id"
            ") VALUES (?, ?, ?, 'contra', ?, ?, ?, ?, ?, ?, ?)",
            (
                posting_id,
                stx_id,
                effective_srec,
                idx,
                account,
                p["minor_units"],
                p.get("currency", imp_curr),
                p.get("scale", imp_scale),
                now_utc,
                ledger_id,
            ),
        )


def confirm_split_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    actor: str = "operator",
    now_utc: str | None = None,
) -> dict:
    """Confirm a split proposal and mutate staged postings transactionally."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    prop = conn.execute(
        "SELECT sp.proposal_id, sp.order_id, sp.target_type, sp.target_id, sp.status, "
        "       sp.selected_line_indices, sp.allocated_tax_minor, sp.allocated_shipping_minor, sp.allocated_discount_minor, "
        "       io.source_document_id, io.currency, io.tax_minor_units, io.shipping_minor_units, io.discount_minor_units, io.ledger_id "
        "FROM split_proposals sp "
        "JOIN itemized_orders io ON sp.order_id = io.order_id "
        "WHERE sp.proposal_id = ?",
        (proposal_id,),
    ).fetchone()

    if not prop:
        raise ValueError(f"Split proposal {proposal_id} not found")

    (
        p_id,
        order_id,
        target_type,
        target_id,
        status,
        selected_line_indices,
        allocated_tax_minor,
        allocated_shipping_minor,
        allocated_discount_minor,
        source_doc_id,
        currency,
        tax_minor,
        shipping_minor,
        discount_minor,
        ledger_id,
    ) = prop

    if status == "confirmed":
        return {"status": "confirmed", "proposal_id": proposal_id, "target_id": target_id}
    if status == "rejected":
        raise ValueError(f"Cannot confirm already rejected proposal {proposal_id}")

    if target_type == "staged_transaction":
        # Load order lines
        lines = conn.execute(
            "SELECT line_index, item_title, total_price_minor, proposed_account "
            "FROM itemized_order_lines WHERE order_id = ? ORDER BY line_index",
            (order_id,),
        ).fetchall()
        selected = set(json.loads(selected_line_indices)) if selected_line_indices else None
        lines = [line for line in lines if selected is None or line[0] in selected]
        effective_tax = allocated_tax_minor if selected is not None and allocated_tax_minor is not None else tax_minor
        effective_shipping = allocated_shipping_minor if selected is not None and allocated_shipping_minor is not None else shipping_minor
        effective_discount = allocated_discount_minor if selected is not None and allocated_discount_minor is not None else discount_minor

        contra_postings: list[dict] = []
        for _line_index, _title, total_price, account in lines:
            contra_postings.append({
                "account": account,
                "minor_units": total_price,
                "currency": currency,
                "scale": 2,
            })

        # Add remaining tax/shipping/discount legs if not 0
        if effective_tax > 0:
            contra_postings.append({
                "account": "Expenses:Taxes",
                "minor_units": effective_tax,
                "currency": currency,
                "scale": 2,
            })
        if effective_shipping > 0:
            contra_postings.append({
                "account": "Expenses:Shipping",
                "minor_units": effective_shipping,
                "currency": currency,
                "scale": 2,
            })
        if effective_discount > 0:
            contra_postings.append({
                "account": "Income:Discounts",
                "minor_units": -effective_discount,
                "currency": currency,
                "scale": 2,
            })

        apply_staged_transaction_split(conn, target_id, contra_postings, now_utc=now_utc)

        # Update proposal status
        conn.execute(
            "UPDATE split_proposals SET status = 'confirmed', decided_at_utc = ? WHERE proposal_id = ?",
            (now_utc, proposal_id),
        )

        # Record audit event
        append_audit_event(
            conn,
            actor=actor,
            action="split proposal confirm",
            target=proposal_id,
            result="ok",
            ts_utc=now_utc,
        )

        conn.commit()
        return {"status": "confirmed", "proposal_id": proposal_id, "target_id": target_id}

    raise NotImplementedError(f"Target type {target_type} not implemented")


def reject_split_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    actor: str = "operator",
    now_utc: str | None = None,
) -> dict:
    """Reject a split proposal."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    prop = conn.execute(
        "SELECT proposal_id, status FROM split_proposals WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()

    if not prop:
        raise ValueError(f"Split proposal {proposal_id} not found")

    conn.execute(
        "UPDATE split_proposals SET status = 'rejected', decided_at_utc = ? WHERE proposal_id = ?",
        (now_utc, proposal_id),
    )
    append_audit_event(
        conn,
        actor=actor,
        action="split proposal reject",
        target=proposal_id,
        result="ok",
        ts_utc=now_utc,
    )
    conn.commit()
    return {"status": "rejected", "proposal_id": proposal_id}
