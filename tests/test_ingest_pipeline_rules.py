"""Phase 2b: import consults categorization rules and takes --importing-account for OFX."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.errors import ParseError
from ironledger.ingest.pipeline import run_import
from ironledger.review.rules import add_rule

FIXTURES = Path(__file__).parent / "fixtures"
CSV_IMPORTED_ACCOUNT = "Assets:Bank:Checking:ExampleBank"  # from config/csv-profiles/example-bank.json
OFX_IMPORTING_ACCOUNT = "Assets:Bank:Checking:SampleOfx"


@pytest.fixture
def env(tmp_path: Path):
    conn = connect(str(tmp_path / "ledger.db"))
    migrations.migrate(conn)
    config_dir = tmp_path / "config"
    (config_dir / "csv-profiles").mkdir(parents=True)
    (config_dir / "csv-profiles" / "example-bank.json").write_text(
        Path("config/csv-profiles/example-bank.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    paths = {
        "config_dir": config_dir,
        "evidence_dir": tmp_path / "evidence",
        "records_dir": tmp_path / "evidence" / "source_records",
    }
    return conn, paths


def _contra(conn, stx_like="stx:%"):
    return conn.execute(
        "SELECT account FROM staged_postings WHERE role = 'contra' ORDER BY staged_posting_id"
    ).fetchall()


def _last_import_action(conn) -> str:
    return conn.execute(
        "SELECT action FROM audit_events WHERE action LIKE 'import%' ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0]


def test_matching_rule_fills_contra_and_row_stays_pending(env):
    conn, paths = env
    # sample_bank.csv row 1 payee is "COFFEE BAR" -> canonical "coffee bar";
    # the profile's imported account is Assets:Bank:Checking:ExampleBank.
    add_rule(conn, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             importing_account=CSV_IMPORTED_ACCOUNT, now_utc="2026-09-03T09:00:00Z")
    conn.commit()
    run_import(conn, FIXTURES / "sample_bank.csv", csv_profile="example-bank",
               now_utc="2026-09-03T10:00:00Z", **paths)
    filled = conn.execute(
        "SELECT p.account FROM staged_postings p JOIN staged_transactions t "
        "  ON t.staged_transaction_id = p.staged_transaction_id "
        "WHERE p.role = 'contra' AND t.payee = 'COFFEE BAR'"
    ).fetchone()[0]
    status = conn.execute(
        "SELECT status FROM staged_transactions WHERE payee = 'COFFEE BAR'"
    ).fetchone()[0]
    assert filled == "Expenses:Coffee"
    assert status == "pending"
    assert "rules_applied=1" in _last_import_action(conn)


def test_no_matching_rule_leaves_contra_null(env):
    conn, paths = env
    run_import(conn, FIXTURES / "sample_bank.csv", csv_profile="example-bank",
               now_utc="2026-09-03T10:00:00Z", **paths)
    nulls = conn.execute(
        "SELECT count(*) FROM staged_postings WHERE role = 'contra' AND account IS NULL"
    ).fetchone()[0]
    assert nulls == 3  # every row in sample_bank.csv
    assert "rules_applied=0" in _last_import_action(conn)


def test_reimport_after_rule_change_is_a_noop(env):
    conn, paths = env
    run_import(conn, FIXTURES / "sample_bank.csv", csv_profile="example-bank",
               now_utc="2026-09-03T10:00:00Z", **paths)
    add_rule(conn, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             importing_account=CSV_IMPORTED_ACCOUNT, now_utc="2026-09-03T10:30:00Z")
    conn.commit()
    result = run_import(conn, FIXTURES / "sample_bank.csv", csv_profile="example-bank",
                        now_utc="2026-09-03T11:00:00Z", **paths)
    assert result.records_created == 0 and result.short_circuited is True
    coffee_contra = conn.execute(
        "SELECT p.account FROM staged_postings p JOIN staged_transactions t "
        "  ON t.staged_transaction_id = p.staged_transaction_id "
        "WHERE p.role = 'contra' AND t.payee = 'COFFEE BAR'"
    ).fetchone()[0]
    assert coffee_contra is None  # the pre-existing fingerprint short-circuits; no rewrite


def test_ofx_without_importing_account_is_a_parse_error(env):
    conn, paths = env
    with pytest.raises(ParseError):
        run_import(conn, FIXTURES / "sample_v1.ofx", csv_profile=None,
                   now_utc="2026-09-03T10:00:00Z", **paths)
    assert conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0] == 0


def test_csv_with_importing_account_is_a_parse_error(env):
    conn, paths = env
    with pytest.raises(ParseError):
        run_import(conn, FIXTURES / "sample_bank.csv", csv_profile="example-bank",
                   importing_account="Assets:Bank:Checking:Wrong",
                   now_utc="2026-09-03T10:00:00Z", **paths)
    assert conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0] == 0


def test_ofx_import_with_importing_account_and_rule_fills_contra(env):
    conn, paths = env
    add_rule(conn, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             importing_account=OFX_IMPORTING_ACCOUNT, now_utc="2026-09-03T09:00:00Z")
    conn.commit()
    run_import(conn, FIXTURES / "sample_v1.ofx", csv_profile=None,
               importing_account=OFX_IMPORTING_ACCOUNT, now_utc="2026-09-03T10:00:00Z", **paths)
    coffee_contra = conn.execute(
        "SELECT p.account FROM staged_postings p JOIN staged_transactions t "
        "  ON t.staged_transaction_id = p.staged_transaction_id "
        "WHERE p.role = 'contra' AND t.payee = 'COFFEE BAR'"
    ).fetchone()[0]
    imported = conn.execute(
        "SELECT DISTINCT account FROM staged_postings WHERE role = 'imported'"
    ).fetchall()
    assert coffee_contra == "Expenses:Coffee"
    assert imported == [(OFX_IMPORTING_ACCOUNT,)]  # no fabricated Assets:Unmapped:* name
