# tests/test_migration_0004_rules.py
"""Phase 2b: migration 0004 adds the categorization_rules table."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _add(conn, rule_id, match_type="exact", pattern="coffee bar",
         importing_account=None, target_account="Expenses:Coffee", priority=100):
    conn.execute(
        "INSERT INTO categorization_rules (rule_id, match_type, pattern, importing_account, "
        " target_account, priority, active, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (rule_id, match_type, pattern, importing_account, target_account, priority,
         "2026-09-03T10:00:00Z"),
    )


def test_table_exists_and_accepts_a_row(db: sqlite3.Connection):
    _add(db, "r1")
    db.commit()
    assert db.execute("SELECT count(*) FROM categorization_rules").fetchone()[0] == 1


def test_match_type_check(db: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError):
        _add(db, "r-bad", match_type="glob")


def test_target_account_root_check(db: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError):
        _add(db, "r-bad", target_account="Nonsense:Root")


def test_unique_on_match_pattern_and_scope(db: sqlite3.Connection):
    _add(db, "r1", importing_account="Assets:Bank:Checking")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _add(db, "r2", importing_account="Assets:Bank:Checking")
        db.commit()


def test_null_scope_is_distinct_from_a_concrete_account(db: sqlite3.Connection):
    _add(db, "r-global", importing_account=None)
    _add(db, "r-scoped", importing_account="Assets:Bank:Checking")
    db.commit()
    assert db.execute("SELECT count(*) FROM categorization_rules").fetchone()[0] == 2


def test_active_priority_index_present(db: sqlite3.Connection):
    names = {r[1] for r in db.execute("PRAGMA index_list('categorization_rules')")}
    assert "idx_categorization_rules_active_priority" in names
