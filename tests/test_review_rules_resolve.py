"""Phase 2b: categorization rule resolution — match types, priority, scope, skip-on-bad-regex."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.identity import canonical_payee
from ironledger.review.rules import resolve_rule


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _add(conn, rule_id, *, match_type, pattern, target, importing_account=None,
         priority=100, active=1, created="2026-09-03T10:00:00Z"):
    conn.execute(
        "INSERT INTO categorization_rules (rule_id, match_type, pattern, importing_account, "
        " target_account, priority, active, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (rule_id, match_type, pattern, importing_account, target, priority, active, created),
    )
    conn.commit()


def test_exact_match(db):
    _add(db, "r1", match_type="exact", pattern="coffee bar", target="Expenses:Coffee")
    assert resolve_rule(db, canonical_payee("Coffee Bar"), "Assets:Bank:Checking") == "Expenses:Coffee"


def test_prefix_match(db):
    _add(db, "r1", match_type="prefix", pattern="amzn mktp", target="Expenses:Shopping")
    assert resolve_rule(db, canonical_payee("AMZN Mktp US*1A2B3"), "Assets:Bank:Checking") == "Expenses:Shopping"


def test_regex_match(db):
    _add(db, "r1", match_type="regex", pattern=r"^uber\s+(eats|trip)", target="Expenses:Transport")
    assert resolve_rule(db, canonical_payee("UBER   Trip 123"), "Assets:Bank:Checking") == "Expenses:Transport"


def test_no_match_returns_none(db):
    _add(db, "r1", match_type="exact", pattern="coffee bar", target="Expenses:Coffee")
    assert resolve_rule(db, canonical_payee("Gas Station"), "Assets:Bank:Checking") is None


def test_priority_then_created_at_ordering(db):
    _add(db, "low-prio", match_type="prefix", pattern="star", target="Expenses:A", priority=100,
         created="2026-09-03T10:00:00Z")
    _add(db, "high-prio", match_type="prefix", pattern="star", target="Expenses:B", priority=50,
         created="2026-09-03T11:00:00Z")
    assert resolve_rule(db, canonical_payee("Starbucks"), "Assets:Bank:Checking") == "Expenses:B"


def test_importing_account_scope(db):
    _add(db, "scoped", match_type="exact", pattern="transfer", target="Assets:Savings",
         importing_account="Assets:Bank:Checking")
    assert resolve_rule(db, canonical_payee("Transfer"), "Assets:Bank:Other") is None
    assert resolve_rule(db, canonical_payee("Transfer"), "Assets:Bank:Checking") == "Assets:Savings"


def test_inactive_rule_skipped(db):
    _add(db, "r1", match_type="exact", pattern="coffee bar", target="Expenses:Coffee", active=0)
    assert resolve_rule(db, canonical_payee("Coffee Bar"), "Assets:Bank:Checking") is None


def test_uncompilable_regex_is_skipped_and_audited(db):
    _add(db, "bad", match_type="regex", pattern="(unclosed", target="Expenses:X", priority=10)
    _add(db, "ok", match_type="exact", pattern="coffee bar", target="Expenses:Coffee", priority=20)
    assert resolve_rule(db, canonical_payee("Coffee Bar"), "Assets:Bank:Checking") == "Expenses:Coffee"
    row = db.execute(
        "SELECT action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row == ("rule resolve (skipped uncompilable regex)", "bad", "error")


def test_uncompilable_regex_with_audit_skips_false_writes_nothing(db):
    _add(db, "bad", match_type="regex", pattern="(unclosed", target="Expenses:X", priority=10)
    _add(db, "ok", match_type="exact", pattern="coffee bar", target="Expenses:Coffee", priority=20)
    before = db.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    assert resolve_rule(
        db, canonical_payee("Coffee Bar"), "Assets:Bank:Checking", audit_skips=False
    ) == "Expenses:Coffee"
    assert db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == before
