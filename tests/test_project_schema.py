# tests/test_project_schema.py
from __future__ import annotations

import sqlite3

import pytest

from ironledger.db.connection import connect
from ironledger.project.migrate import PROJECT_SCHEMA_VERSION, apply_schema


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "projection.sqlite")
    apply_schema(c)
    return c


def test_schema_version_constant():
    assert PROJECT_SCHEMA_VERSION == 1


def test_tables_exist(conn: sqlite3.Connection):
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert "projection_meta" in names
    assert "proj_accounts" in names
    assert "proj_entries" in names
    assert "proj_postings" in names
    assert "proj_balances" in names
    assert "proj_fts" in names


def test_projection_meta_accepts_exactly_one_row(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO projection_meta (singleton, compile_run_id, ledger_input_hash, "
        " ledger_output_hash, schema_version, built_at_utc, beancount_version, compiler_version) "
        "VALUES (1, 'run-1', ?, ?, 1, '2026-09-08T12:00:00Z', '3.2.3', '0.1.0')",
        ("a" * 64, "b" * 64),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projection_meta (singleton, compile_run_id, ledger_input_hash, "
            " ledger_output_hash, schema_version, built_at_utc, beancount_version, compiler_version) "
            "VALUES (1, 'run-2', ?, ?, 1, '2026-09-08T12:00:00Z', '3.2.3', '0.1.0')",
            ("c" * 64, "d" * 64),
        )


def test_posting_fk_and_entry_unique(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO proj_entries (entry_id, entry_date, payee, narration, staged_transaction_id) "
        "VALUES ('stx-1', '2026-09-01', 'Cafe', 'Latte', 'stx-1')"
    )
    conn.execute(
        "INSERT INTO proj_postings (posting_id, entry_id, account, minor_units, currency, "
        " minor_unit_scale, source_document_id, source_record_id, identity_algo_version, identity_method) "
        "VALUES ('stx-1:imported', 'stx-1', 'Assets:Checking', -1234, 'USD', 2, 'doc-1', 'rec-1', 1, 'fitid')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO proj_entries (entry_id, entry_date, payee, narration, staged_transaction_id) "
            "VALUES ('stx-2', '2026-09-01', 'X', 'Y', 'stx-1')"
        )
