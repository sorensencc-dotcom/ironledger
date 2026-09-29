from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from ironledger.db.connection import connect
from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.amazon_order_normalizer import (
    ParsedItemizedOrder,
    ParsedOrderLine,
)
from ironledger.ingest.split_linker import (
    categorize_order_line,
    propose_splits_for_order,
    confirm_split_proposal,
    reject_split_proposal,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test_split.db"
    conn = connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)
    return conn


def _seed_environment(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO source_documents ("
        "  source_document_id, mime_type, encoding, provenance, "
        "  acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc"
        ") VALUES ("
        "  'doc_stmt_001', 'text/csv', 'utf-8', 'amex_statement', "
        "  '2026-09-29T12:00:00Z', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
        "  'evidence/amex.csv', '2026-09-29T12:00:00Z'"
        ")"
    )
    conn.execute(
        "INSERT INTO source_records ("
        "  source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc"
        ") VALUES ("
        "  'rec_stx_001', 'doc_stmt_001', 0, '{\"amount\": -5410}', "
        "  'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2026-09-29T12:00:00Z'"
        ")"
    )
    conn.execute(
        "INSERT INTO staged_transactions ("
        "  staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        "  identity_algo_version, identity_method, identity_fingerprint, created_at_utc, ledger_id"
        ") VALUES ("
        "  'stx_amazon_001', 'rec_stx_001', 'pending', '2026-09-29', 'AMZN Mktp US', 'Amazon order', "
        "  1, 'sha256_fallback', 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', "
        "  '2026-09-29T12:00:00Z', 'default'"
        ")"
    )
    conn.execute(
        "INSERT INTO staged_postings ("
        "  staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, "
        "  account, minor_units, currency, minor_unit_scale, created_at_utc, ledger_id"
        ") VALUES ("
        "  'sp_imp_001', 'stx_amazon_001', 'rec_stx_001', 'imported', 0, "
        "  'Liabilities:CreditCard:Amex', -5410, 'USD', 2, '2026-09-29T12:00:00Z', 'default'"
        "), ("
        "  'sp_contra_001', 'stx_amazon_001', 'rec_stx_001', 'contra', 1, "
        "  'Expenses:Shopping', 5410, 'USD', 2, '2026-09-29T12:00:00Z', 'default'"
        ")"
    )
    conn.execute(
        "INSERT INTO source_documents ("
        "  source_document_id, mime_type, encoding, provenance, "
        "  acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc"
        ") VALUES ("
        "  'doc_ord_001', 'text/csv', 'utf-8', 'amazon_orders', "
        "  '2026-09-29T12:00:00Z', 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', "
        "  'evidence/amazon.csv', '2026-09-29T12:00:00Z'"
        ")"
    )
    conn.commit()


def test_3_tier_categorization_heuristic_and_fallback(db: sqlite3.Connection):
    _seed_environment(db)
    # Tier 2 Heuristic: Book
    acct, conf = categorize_order_line(db, "Clean Architecture Paperback", "", "Amazon")
    assert acct == "Expenses:Books"
    assert conf >= 80

    # Tier 2 Heuristic: Electronics
    acct, conf = categorize_order_line(db, "USB-C Fast Charging Cable", "", "Amazon")
    assert acct == "Expenses:Electronics"
    assert conf >= 80

    # Tier 3 Fallback: Random unknown item
    acct, conf = categorize_order_line(db, "Xylophone Widget 9000", "", "Amazon")
    assert acct == "Expenses:Uncategorized"
    assert conf == 50


def test_propose_splits_and_confirm_lifecycle(db: sqlite3.Connection):
    _seed_environment(db)
    order = ParsedItemizedOrder(
        order_id="ord_amazon_001",
        merchant="Amazon",
        merchant_order_ref="114-1234567-8901234",
        order_date="2026-09-29",
        currency="USD",
        subtotal_minor_units=5000,
        tax_minor_units=410,
        shipping_minor_units=0,
        discount_minor_units=0,
        total_minor_units=5410,
        lines=(
            ParsedOrderLine(0, "Designing Data-Intensive Applications", "", 1, 3000, 3000, "Expenses:Books", 90),
            ParsedOrderLine(1, "Anker USB-C Hub 7-in-1", "", 1, 2000, 2000, "Expenses:Electronics", 90),
        ),
    )

    # Propose split
    proposal_id = propose_splits_for_order(db, order, source_document_id="doc_ord_001", ledger_id="default")
    assert proposal_id is not None

    prop = db.execute("SELECT target_id, match_confidence, status FROM split_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
    assert prop[0] == "stx_amazon_001"
    assert prop[1] >= 90
    assert prop[2] == "pending"

    # Confirm split
    res = confirm_split_proposal(db, proposal_id, actor="operator")
    assert res["status"] == "confirmed"

    # Verify staged_postings mutated properly
    postings = db.execute(
        "SELECT role, account, minor_units FROM staged_postings WHERE staged_transaction_id = 'stx_amazon_001' ORDER BY posting_index"
    ).fetchall()

    # 1 imported (-5410) + 2 contra items (+3000, +2000) + 1 tax contra (+410)
    assert postings[0] == ("imported", "Liabilities:CreditCard:Amex", -5410)
    contra_legs = [p for p in postings if p[0] == "contra"]
    assert len(contra_legs) >= 2
    total_contra = sum(p[2] for p in contra_legs)
    assert total_contra == 5410
    assert sum(p[2] for p in postings) == 0


def test_reject_split_proposal(db: sqlite3.Connection):
    _seed_environment(db)
    order = ParsedItemizedOrder(
        order_id="ord_amazon_002",
        merchant="Amazon",
        merchant_order_ref="114-9999999",
        order_date="2026-09-29",
        currency="USD",
        subtotal_minor_units=5410,
        tax_minor_units=0,
        shipping_minor_units=0,
        discount_minor_units=0,
        total_minor_units=5410,
        lines=(
            ParsedOrderLine(0, "Item 1", "", 1, 5410, 5410, "Expenses:Household", 80),
        ),
    )
    proposal_id = propose_splits_for_order(db, order, source_document_id="doc_ord_001", ledger_id="default")
    assert proposal_id is not None

    res = reject_split_proposal(db, proposal_id, actor="operator")
    assert res["status"] == "rejected"

    status = db.execute("SELECT status FROM split_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()[0]
    assert status == "rejected"
