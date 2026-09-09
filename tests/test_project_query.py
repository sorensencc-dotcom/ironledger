# tests/test_project_query.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.project.errors import ProjectInputError, ProjectStaleError
from ironledger.project.query import assert_fresh, balances, search
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def live(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir)
    conn = connect(str(db_path))
    migrations.migrate(conn)
    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    return ledger_dir, projection_dir


def test_search_hits_payee_and_is_stable(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    rows1 = search(conn, "Coffee")
    rows2 = search(conn, "Coffee")
    assert rows1 == rows2
    assert len(rows1) >= 1
    assert rows1[0].account in {"Assets:Checking", "Expenses:Food"}
    assert rows1[0].staged_transaction_id == "stx-1"
    ordered = search(conn, "Coffee")
    assert [h.posting_id for h in ordered] == sorted(
        (h.posting_id for h in ordered),
        key=lambda pid: (next(x.entry_date for x in ordered if x.posting_id == pid), pid),
    )
    conn.close()


def test_search_order_date_then_posting_id(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    hits = search(conn, "USD")
    pairs = [(h.entry_date, h.posting_id) for h in hits]
    assert pairs == sorted(pairs)
    conn.close()


def test_empty_and_invalid_match(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    with pytest.raises(ProjectInputError, match="empty"):
        search(conn, "  ")
    with pytest.raises(ProjectInputError, match="invalid"):
        search(conn, "AND")
    conn.close()


def test_balances_one_line_per_account_currency(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    rows = balances(conn)
    assert [(r.account, r.currency) for r in rows] == sorted(
        (r.account, r.currency) for r in rows
    )
    checking = next(r for r in rows if r.account == "Assets:Checking")
    food = next(r for r in rows if r.account == "Expenses:Food")
    assert checking.minor_units == -1234
    assert food.minor_units == 1234
    conn.close()


def test_assert_fresh_missing_projection(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    with pytest.raises(ProjectStaleError):
        assert_fresh(ledger_dir, tmp_path / "projection")
