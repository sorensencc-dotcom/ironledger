"""Phase 2b: rule add / disable / list / persist_exact_rule."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.review.rules import (
    RuleError,
    RuleExistsError,
    add_rule,
    disable_rule,
    list_rules,
    persist_exact_rule,
    resolve_rule,
)
from ironledger.ingest.identity import canonical_payee


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_add_rule_persists_and_audits(db):
    rid = add_rule(db, match_type="prefix", pattern="amzn mktp", target_account="Expenses:Shopping",
                   now_utc="2026-09-03T10:00:00Z")
    db.commit()
    assert resolve_rule(db, canonical_payee("AMZN Mktp 12"), "Assets:Bank:Checking") == "Expenses:Shopping"
    action, target = db.execute(
        "SELECT action, target FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert action == "rule add (prefix amzn mktp -> Expenses:Shopping)"
    assert target == rid


def test_add_rule_rejects_bad_match_type(db):
    with pytest.raises(RuleError):
        add_rule(db, match_type="glob", pattern="x", target_account="Expenses:X")


def test_add_rule_rejects_uncompilable_regex(db):
    with pytest.raises(RuleError):
        add_rule(db, match_type="regex", pattern="(unclosed", target_account="Expenses:X")


def test_add_rule_rejects_bad_account(db):
    with pytest.raises(RuleError):
        add_rule(db, match_type="exact", pattern="x", target_account="NotARoot:X")


def test_disable_rule(db):
    rid = add_rule(db, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
                   now_utc="2026-09-03T10:00:00Z")
    db.commit()
    disable_rule(db, rid, now_utc="2026-09-03T11:00:00Z")
    db.commit()
    assert resolve_rule(db, canonical_payee("Coffee Bar"), "Assets:Bank:Checking") is None
    active, disabled_at = db.execute(
        "SELECT active, disabled_at_utc FROM categorization_rules WHERE rule_id = ?", (rid,)
    ).fetchone()
    assert active == 0
    assert disabled_at == "2026-09-03T11:00:00Z"


def test_disable_unknown_or_already_disabled_raises(db):
    with pytest.raises(RuleError):
        disable_rule(db, "rule:nope")
    rid = add_rule(db, match_type="exact", pattern="x", target_account="Expenses:X")
    db.commit()
    disable_rule(db, rid)
    db.commit()
    with pytest.raises(RuleError):
        disable_rule(db, rid)


def test_list_rules_shape_and_order(db):
    add_rule(db, match_type="prefix", pattern="b", target_account="Expenses:B", priority=100,
             now_utc="2026-09-03T10:00:00Z")
    add_rule(db, match_type="prefix", pattern="a", target_account="Expenses:A", priority=50,
             now_utc="2026-09-03T10:01:00Z")
    db.commit()
    rules = list_rules(db)
    assert [r["pattern"] for r in rules] == ["a", "b"]
    assert set(rules[0]) == {
        "rule_id", "match_type", "pattern", "importing_account", "target_account",
        "priority", "active", "created_at_utc", "disabled_at_utc",
    }


def test_persist_exact_rule_writes_scoped_priority_50(db):
    rid = persist_exact_rule(
        db, canonical_payee_value=canonical_payee("Coffee Bar"),
        importing_account="Assets:Bank:Checking", target_account="Expenses:Coffee",
        now_utc="2026-09-03T10:00:00Z",
    )
    db.commit()
    row = db.execute(
        "SELECT match_type, pattern, importing_account, target_account, priority FROM categorization_rules "
        "WHERE rule_id = ?", (rid,)
    ).fetchone()
    assert row == ("exact", "coffee bar", "Assets:Bank:Checking", "Expenses:Coffee", 50)


def test_persist_exact_rule_collision_raises_with_existing_id(db):
    first = persist_exact_rule(
        db, canonical_payee_value="coffee bar", importing_account="Assets:Bank:Checking",
        target_account="Expenses:Coffee", now_utc="2026-09-03T10:00:00Z",
    )
    db.commit()
    with pytest.raises(RuleExistsError) as exc:
        persist_exact_rule(
            db, canonical_payee_value="coffee bar", importing_account="Assets:Bank:Checking",
            target_account="Expenses:Other", now_utc="2026-09-03T11:00:00Z",
        )
    assert exc.value.existing_rule_id == first
