from __future__ import annotations

import sqlite3
import pytest
from pathlib import Path

from ironledger.db.connection import connect
from ironledger.governance.migrations import migrate_governed


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)
    return conn


def _seed_base_data(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO source_documents ("
        "  source_document_id, mime_type, encoding, provenance, "
        "  acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc"
        ") VALUES ("
        "  'doc_order_001', 'text/csv', 'utf-8', 'amazon_orders', "
        "  '2026-09-29T12:00:00Z', '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef', "
        "  'evidence/orders/order.csv', '2026-09-29T12:00:00Z'"
        ")"
    )
    conn.commit()


def test_migration_0021_tables_exist(db_conn: sqlite3.Connection):
    tables = {r[0] for r in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "itemized_orders" in tables
    assert "itemized_order_lines" in tables
    assert "split_proposals" in tables


def test_migration_0021_valid_insert(db_conn: sqlite3.Connection):
    _seed_base_data(db_conn)
    db_conn.execute(
        "INSERT INTO itemized_orders ("
        "  order_id, source_document_id, ledger_id, merchant, merchant_order_ref, "
        "  order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, "
        "  discount_minor_units, total_minor_units, created_at_utc"
        ") VALUES ("
        "  'ord_001', 'doc_order_001', 'default', 'Amazon', '112-1234567-8901234', "
        "  '2026-09-29', 'USD', 9500, 1000, 500, 500, 10500, '2026-09-29T12:00:00Z'"
        ")"
    )
    db_conn.execute(
        "INSERT INTO itemized_order_lines ("
        "  line_id, order_id, line_index, item_title, item_description, "
        "  quantity, unit_price_minor, total_price_minor, proposed_account, confidence_score, created_at_utc"
        ") VALUES ("
        "  'line_001', 'ord_001', 0, 'Clean Architecture Book', 'Hardcover book', "
        "  1, 3500, 3500, 'Expenses:Books', 95, '2026-09-29T12:00:00Z'"
        ")"
    )
    db_conn.execute(
        "INSERT INTO split_proposals ("
        "  proposal_id, order_id, target_type, target_id, parent_amount_minor, match_confidence, status, created_at_utc"
        ") VALUES ("
        "  'prop_001', 'ord_001', 'staged_transaction', 'stx_parent_001', -10500, 98, 'pending', '2026-09-29T12:00:00Z'"
        ")"
    )
    db_conn.commit()

    order = db_conn.execute("SELECT total_minor_units FROM itemized_orders WHERE order_id = 'ord_001'").fetchone()
    assert order[0] == 10500


def test_migration_0021_check_total_balance_constraint(db_conn: sqlite3.Connection):
    _seed_base_data(db_conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        db_conn.execute(
            "INSERT INTO itemized_orders ("
            "  order_id, source_document_id, ledger_id, merchant, merchant_order_ref, "
            "  order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, "
            "  discount_minor_units, total_minor_units, created_at_utc"
            ") VALUES ("
            "  'ord_fail', 'doc_order_001', 'default', 'Amazon', '112-9999999', "
            "  '2026-09-29', 'USD', 5000, 500, 0, 0, 6000, '2026-09-29T12:00:00Z'"  # 5000 + 500 = 5500 != 6000
            ")"
        )


def test_migration_0021_fk_violation_missing_document(db_conn: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        db_conn.execute(
            "INSERT INTO itemized_orders ("
            "  order_id, source_document_id, ledger_id, merchant, merchant_order_ref, "
            "  order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, "
            "  discount_minor_units, total_minor_units, created_at_utc"
            ") VALUES ("
            "  'ord_no_doc', 'doc_nonexistent', 'default', 'Amazon', '112-0000000', "
            "  '2026-09-29', 'USD', 1000, 0, 0, 0, 1000, '2026-09-29T12:00:00Z'"
            ")"
        )


def test_migration_0021_cascade_deletion(db_conn: sqlite3.Connection):
    _seed_base_data(db_conn)
    db_conn.execute(
        "INSERT INTO itemized_orders ("
        "  order_id, source_document_id, ledger_id, merchant, merchant_order_ref, "
        "  order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, "
        "  discount_minor_units, total_minor_units, created_at_utc"
        ") VALUES ("
        "  'ord_cascade', 'doc_order_001', 'default', 'Amazon', '112-1111111', "
        "  '2026-09-29', 'USD', 1000, 0, 0, 0, 1000, '2026-09-29T12:00:00Z'"
        ")"
    )
    db_conn.execute(
        "INSERT INTO itemized_order_lines ("
        "  line_id, order_id, line_index, item_title, item_description, "
        "  quantity, unit_price_minor, total_price_minor, proposed_account, confidence_score, created_at_utc"
        ") VALUES ("
        "  'line_cascade', 'ord_cascade', 0, 'Test item', '', "
        "  1, 1000, 1000, 'Expenses:Household', 80, '2026-09-29T12:00:00Z'"
        ")"
    )
    db_conn.execute("DELETE FROM itemized_orders WHERE order_id = 'ord_cascade'")
    db_conn.commit()

    lines = db_conn.execute("SELECT count(*) FROM itemized_order_lines WHERE order_id = 'ord_cascade'").fetchone()[0]
    assert lines == 0


def test_migration_0021_proposal_unique_target_constraint(db_conn: sqlite3.Connection):
    _seed_base_data(db_conn)
    db_conn.execute(
        "INSERT INTO itemized_orders ("
        "  order_id, source_document_id, ledger_id, merchant, merchant_order_ref, "
        "  order_date, currency, subtotal_minor_units, tax_minor_units, shipping_minor_units, "
        "  discount_minor_units, total_minor_units, created_at_utc"
        ") VALUES ("
        "  'ord_uniq', 'doc_order_001', 'default', 'Amazon', '112-2222222', "
        "  '2026-09-29', 'USD', 1000, 0, 0, 0, 1000, '2026-09-29T12:00:00Z'"
        ")"
    )
    db_conn.execute(
        "INSERT INTO split_proposals ("
        "  proposal_id, order_id, target_type, target_id, parent_amount_minor, match_confidence, status, created_at_utc"
        ") VALUES ("
        "  'prop_uniq_1', 'ord_uniq', 'staged_transaction', 'stx_same_001', -1000, 95, 'pending', '2026-09-29T12:00:00Z'"
        ")"
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        db_conn.execute(
            "INSERT INTO split_proposals ("
            "  proposal_id, order_id, target_type, target_id, parent_amount_minor, match_confidence, status, created_at_utc"
            ") VALUES ("
            "  'prop_uniq_2', 'ord_uniq', 'staged_transaction', 'stx_same_001', -1000, 95, 'pending', '2026-09-29T12:00:00Z'"
            ")"
        )
