# tests/test_compile_model.py
"""Tests for loading and validating the approved transaction set for compilation."""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.errors import CompileInputError
from ironledger.compile.model import load_approved_set, validate_approved_set, ApprovedSet


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_approved(conn: sqlite3.Connection, *, contra_account="Expenses:Food", minor_units=1500, currency="USD", date="2026-09-01", tx_id="stx-1") -> str:
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1','text/csv','utf-8','prov','2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        " identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('{tx_id}', 'rec-1', 'approved', '{date}', 'Store', 'Groceries', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    contra_val = f"'{contra_account}'" if contra_account is not None else "NULL"
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        f"VALUES ('sp-1', '{tx_id}', 'rec-1', 'imported', 0, 'Assets:Checking', -{minor_units}, '{currency}', 2, '2026-09-01T10:00:00Z'), "
        f"       ('sp-2', '{tx_id}', 'rec-1', 'contra', 1, {contra_val}, {minor_units}, '{currency}', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()
    return tx_id


def test_load_valid_approved_set(db: sqlite3.Connection):
    _seed_approved(db)
    approved_set = load_approved_set(db)
    assert len(approved_set.transactions) == 1
    tx = approved_set.transactions[0]
    assert tx.staged_transaction_id == "stx-1"
    assert tx.payee == "Store"
    assert len(tx.postings) == 2
    assert tx.postings[0].account == "Assets:Checking"
    assert tx.postings[1].account == "Expenses:Food"
    validate_approved_set(approved_set)


def test_refuse_null_contra_account(db: sqlite3.Connection):
    _seed_approved(db, contra_account=None)
    approved_set = load_approved_set(db)
    with pytest.raises(CompileInputError, match="contra posting has NULL account"):
        validate_approved_set(approved_set)


def test_refuse_unbalanced_transaction(db: sqlite3.Connection):
    _seed_approved(db)
    db.execute("UPDATE staged_postings SET minor_units = 2000 WHERE role = 'contra'")
    db.commit()
    approved_set = load_approved_set(db)
    with pytest.raises(CompileInputError, match="does not balance"):
        validate_approved_set(approved_set)


def test_refuse_account_with_conflicting_currencies(db: sqlite3.Connection):
    _seed_approved(db, tx_id="stx-1", contra_account="Expenses:Food", currency="USD")
    # Seed second transaction for same account with EUR
    db.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-2', 'doc-1', 1, '{{}}', '{'d'*64}', '2026-09-01T10:00:00Z')"
    )
    db.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        " identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-2', 'rec-2', 'approved', '2026-09-02', 'Store EU', '', 1, 'fitid', '{'e'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    db.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-3', 'stx-2', 'rec-2', 'imported', 0, 'Assets:EURChecking', -500, 'EUR', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-4', 'stx-2', 'rec-2', 'contra', 1, 'Expenses:Food', 500, 'EUR', 2, '2026-09-01T10:00:00Z')"
    )
    db.commit()
    approved_set = load_approved_set(db)
    with pytest.raises(CompileInputError, match="multiple currencies"):
        validate_approved_set(approved_set)


def test_refuse_non_imported_contra_role_pair(db: sqlite3.Connection):
    """Finding 4: two 'imported' legs (or any non {imported,contra} pair) is refused."""
    _seed_approved(db)
    db.execute("UPDATE staged_postings SET role = 'imported' WHERE role = 'contra'")
    db.commit()
    with pytest.raises(CompileInputError, match="exactly one 'imported'"):
        validate_approved_set(load_approved_set(db))
