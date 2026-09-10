"""Tests for Hit Confidence Trend (HCT) rule drift tracker and health classification."""

from __future__ import annotations

import sqlite3
import pytest
from datetime import datetime, timezone

from ironledger.governance.drift import (
    RuleDriftMetrics,
    RuleHealthTier,
    audit_all_rules_drift,
    calculate_hct,
    evaluate_rule_drift,
)
import ironledger.governance as gov


def test_hct_calculation():
    # 0 overrides, fresh -> 1.0
    assert calculate_hct(100, 0, 0.0) == 1.0

    # 10% override rate -> 1.0 - (0.10 * 1.5) = 0.85
    assert pytest.approx(calculate_hct(100, 10, 0.0), 0.001) == 0.85

    # Decay over 10 days at lambda = 0.005 -> 0.05 reduction = 0.95
    assert pytest.approx(calculate_hct(100, 0, 10.0), 0.001) == 0.95

    # Combined: 10% overrides and 10 days decay -> 1.0 - 0.15 - 0.05 = 0.80
    assert pytest.approx(calculate_hct(100, 10, 10.0), 0.001) == 0.80

    # Clamping: negative values clamped to 0.0
    assert calculate_hct(100, 90, 0.0) == 0.0
    assert calculate_hct(100, 0, 300.0) == 0.0

    # Zero hits -> override_rate is 0.0, fresh is 1.0
    assert calculate_hct(0, 0, 0.0) == 1.0
    assert pytest.approx(calculate_hct(0, 0, 10.0), 0.001) == 0.95


def test_health_tiering():
    # Low sample count < 5 -> evaluating, provisional is True
    m1 = evaluate_rule_drift("r1", hits=3, overrides=0)
    assert m1.tier == RuleHealthTier.EVALUATING
    assert m1.provisional is True
    assert m1.hct == 1.0

    # hits=0 -> evaluating
    m0 = evaluate_rule_drift("r0", hits=0, overrides=0)
    assert m0.tier == RuleHealthTier.EVALUATING
    assert m0.provisional is True

    # Healthy: hits >= 5, HCT >= 0.80 and O_R < 0.05
    m2 = evaluate_rule_drift("r2", hits=100, overrides=2)
    assert m2.tier == RuleHealthTier.HEALTHY
    assert m2.provisional is False
    assert m2.override_rate == 0.02

    # Warning: 0.05 <= O_R < 0.15
    m3 = evaluate_rule_drift("r3", hits=100, overrides=8)
    assert m3.tier == RuleHealthTier.WARNING
    assert m3.provisional is False

    # Warning: 0.50 <= HCT < 0.80 due to time decay
    m3_decay = evaluate_rule_drift("r3b", hits=100, overrides=2, days_since_last_hit=50.0)
    assert m3_decay.tier == RuleHealthTier.WARNING
    assert m3_decay.provisional is False

    # Critical: O_R >= 0.15
    m4 = evaluate_rule_drift("r4", hits=100, overrides=20)
    assert m4.tier == RuleHealthTier.CRITICAL
    assert m4.provisional is False

    # Critical: HCT < 0.50 due to time decay
    m4_decay = evaluate_rule_drift("r4b", hits=100, overrides=0, days_since_last_hit=120.0)
    assert m4_decay.tier == RuleHealthTier.CRITICAL
    assert m4_decay.provisional is False


def test_health_tiering_boundary_conditions():
    # Boundary: HCT = 0.80, override_rate = 0.04 -> HEALTHY
    # hits=100, overrides=4 -> rate=0.04, 1.0 - 0.06 - 0.14 (28 days) = 0.80
    m_healthy_edge = evaluate_rule_drift("rh", hits=100, overrides=4, days_since_last_hit=28.0)
    assert pytest.approx(m_healthy_edge.hct, 0.001) == 0.80
    assert m_healthy_edge.tier == RuleHealthTier.HEALTHY

    # Boundary: override_rate = 0.05 -> WARNING (even if HCT >= 0.80)
    m_warn_edge = evaluate_rule_drift("rw1", hits=100, overrides=5, days_since_last_hit=0.0)
    assert m_warn_edge.override_rate == 0.05
    assert m_warn_edge.tier == RuleHealthTier.WARNING

    # Boundary: HCT = 0.7999, override_rate = 0.04 -> WARNING
    m_warn_hct = evaluate_rule_drift("rw2", hits=100, overrides=4, days_since_last_hit=29.0)
    assert m_warn_hct.hct < 0.80
    assert m_warn_hct.tier == RuleHealthTier.WARNING

    # Boundary: override_rate = 0.15 -> CRITICAL
    m_crit_edge = evaluate_rule_drift("rc1", hits=100, overrides=15, days_since_last_hit=0.0)
    assert m_crit_edge.override_rate == 0.15
    assert m_crit_edge.tier == RuleHealthTier.CRITICAL

    # Boundary: HCT < 0.50 -> CRITICAL
    m_crit_hct = evaluate_rule_drift("rc2", hits=100, overrides=14, days_since_last_hit=60.0)
    # rate=0.14, 1.0 - 0.21 - 0.30 = 0.49
    assert m_crit_hct.hct < 0.50
    assert m_crit_hct.tier == RuleHealthTier.CRITICAL


def test_evaluate_rule_drift_fields():
    metric = evaluate_rule_drift(
        rule_id="rule-xyz",
        hits=50,
        overrides=5,
        days_since_last_hit=10.0,
        last_hit_utc="2026-09-01T12:00:00Z",
    )
    assert isinstance(metric, RuleDriftMetrics)
    assert metric.rule_id == "rule-xyz"
    assert metric.hits_total == 50
    assert metric.overrides_total == 5
    assert metric.override_rate == 0.10
    assert pytest.approx(metric.hct, 0.001) == 0.80
    assert metric.tier == RuleHealthTier.WARNING
    assert metric.provisional is False
    assert metric.last_hit_utc == "2026-09-01T12:00:00Z"


def test_audit_all_rules_drift_review_rules_table():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE review_rules (
            rule_id TEXT PRIMARY KEY,
            hits INTEGER NOT NULL DEFAULT 0,
            overrides INTEGER NOT NULL DEFAULT 0,
            last_hit_utc TEXT
        )
    """)
    conn.execute(
        "INSERT INTO review_rules (rule_id, hits, overrides, last_hit_utc) VALUES (?, ?, ?, ?)",
        ("rule-1", 100, 2, "2026-09-09T12:00:00Z"),
    )
    conn.execute(
        "INSERT INTO review_rules (rule_id, hits, overrides, last_hit_utc) VALUES (?, ?, ?, ?)",
        ("rule-2", 3, 0, "2026-09-08T12:00:00Z"),
    )
    conn.execute(
        "INSERT INTO review_rules (rule_id, hits, overrides, last_hit_utc) VALUES (?, ?, ?, ?)",
        ("rule-3", 100, 25, "2026-09-07T12:00:00Z"),
    )
    conn.commit()

    results = audit_all_rules_drift(conn, now_utc="2026-09-09T12:00:00Z")
    assert len(results) == 3

    r_map = {r.rule_id: r for r in results}
    assert r_map["rule-1"].tier == RuleHealthTier.HEALTHY
    assert r_map["rule-1"].provisional is False

    assert r_map["rule-2"].tier == RuleHealthTier.EVALUATING
    assert r_map["rule-2"].provisional is True

    assert r_map["rule-3"].tier == RuleHealthTier.CRITICAL
    assert r_map["rule-3"].provisional is False
    conn.close()


def test_audit_all_rules_drift_with_audit_events():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE review_rules (
            rule_id TEXT PRIMARY KEY,
            pattern TEXT,
            target_account TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE audit_events (
            seq INTEGER PRIMARY KEY,
            ts_utc TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            result TEXT NOT NULL
        )
    """)
    conn.execute("INSERT INTO review_rules VALUES ('rule_coffee', 'coffee', 'Expenses:Coffee')")

    # Add 5 hits for rule_coffee
    for i in range(5):
        conn.execute(
            "INSERT INTO audit_events (seq, ts_utc, action, target, result) VALUES (?, ?, ?, ?, ?)",
            (i + 1, f"2026-09-09T10:0{i}:00Z", "review auto-match (Expenses:Coffee; rule rule_coffee)", f"stx_{i}", "ok"),
        )
    # 1 override event
    conn.execute(
        "INSERT INTO audit_events (seq, ts_utc, action, target, result) VALUES (?, ?, ?, ?, ?)",
        (6, "2026-09-09T10:05:00Z", "review override (Expenses:Food; rule rule_coffee)", "stx_5", "ok"),
    )
    conn.commit()

    results = audit_all_rules_drift(conn, now_utc="2026-09-09T10:05:00Z")
    assert len(results) == 1
    m = results[0]
    assert m.rule_id == "rule_coffee"
    assert m.hits_total == 6
    assert m.overrides_total == 1
    assert m.last_hit_utc == "2026-09-09T10:05:00Z"
    # 1 override out of 6 hits -> rate ~ 0.1667 >= 0.15 -> CRITICAL
    assert m.tier == RuleHealthTier.CRITICAL
    conn.close()


def test_audit_all_rules_drift_time_decay():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE review_rules (
            rule_id TEXT PRIMARY KEY,
            hits INTEGER NOT NULL,
            overrides INTEGER NOT NULL,
            last_hit_utc TEXT NOT NULL
        )
    """)
    # 100 hits, 0 overrides, last hit 100 days ago
    conn.execute(
        "INSERT INTO review_rules VALUES (?, ?, ?, ?)",
        ("r_decay", 100, 0, "2026-06-01T00:00:00Z"),
    )
    conn.commit()

    # Query 100 days later: 2026-09-09T00:00:00Z (100 days * 0.005 = 0.50 decay)
    results = audit_all_rules_drift(conn, now_utc="2026-09-09T00:00:00Z")
    assert len(results) == 1
    m = results[0]
    assert m.hits_total == 100
    assert m.overrides_total == 0
    # 1.0 - 0.0 - (0.005 * 100) = 0.50 -> WARNING (since 0.50 <= HCT < 0.80)
    assert pytest.approx(m.hct, 0.001) == 0.50
    assert m.tier == RuleHealthTier.WARNING
    conn.close()


def test_governance_exports():
    assert hasattr(gov, "RuleHealthTier")
    assert hasattr(gov, "RuleDriftMetrics")
    assert hasattr(gov, "calculate_hct")
    assert hasattr(gov, "evaluate_rule_drift")
    assert hasattr(gov, "audit_all_rules_drift")


def test_audit_all_rules_drift_with_categorization_rules_and_staged():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE categorization_rules (
            rule_id TEXT PRIMARY KEY,
            match_type TEXT NOT NULL,
            pattern TEXT NOT NULL,
            target_account TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE staged_transactions (
            staged_transaction_id TEXT PRIMARY KEY,
            payee TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE staged_postings (
            staged_transaction_id TEXT,
            role TEXT,
            account TEXT
        )
    """)
    conn.execute("INSERT INTO categorization_rules VALUES ('rule_uber', 'exact', 'uber', 'Expenses:Transport')")

    # 10 matching staged transactions: 9 matching target account, 1 overridden to Expenses:Travel
    for i in range(9):
        stx = f"tx_{i}"
        conn.execute("INSERT INTO staged_transactions VALUES (?, 'UBER')", (stx,))
        conn.execute("INSERT INTO staged_postings VALUES (?, 'contra', 'Expenses:Transport')", (stx,))

    conn.execute("INSERT INTO staged_transactions VALUES ('tx_override', 'UBER')")
    conn.execute("INSERT INTO staged_postings VALUES ('tx_override', 'contra', 'Expenses:Travel')")
    conn.commit()

    results = audit_all_rules_drift(conn)
    assert len(results) == 1
    m = results[0]
    assert m.rule_id == "rule_uber"
    assert m.hits_total == 10
    assert m.overrides_total == 1
    assert m.override_rate == 0.10
    # 1.0 - 0.15 = 0.85 -> 0.05 <= rate < 0.15 -> WARNING
    assert m.tier == RuleHealthTier.WARNING
    assert m.provisional is False
    conn.close()


def test_audit_all_rules_drift_empty_table():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE review_rules (rule_id TEXT PRIMARY KEY)")
    assert audit_all_rules_drift(conn) == []
    conn.close()


def test_audit_all_rules_drift_missing_table():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(sqlite3.OperationalError):
        audit_all_rules_drift(conn)
    conn.close()

