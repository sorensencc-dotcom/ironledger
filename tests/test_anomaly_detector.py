"""Tests for pure rational anomaly and fraud detection engine."""

from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ironledger.governance.anomaly import (
    AnomalyEngineError,
    NormalizedTransaction,
    compute_flag_id,
    detect_duplicate_charges,
    detect_rational_outliers,
    detect_unusual_payees,
    detect_velocity_spikes,
    resolve_anomaly_flag,
    scan_and_persist_anomalies,
)
from ironledger.governance.migrations import migrate_governed


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test_anomaly.db"
    connection = sqlite3.connect(db_path)
    migrate_governed(connection, db_path)
    try:
        yield connection
    finally:
        connection.close()


def test_ast_zero_float_drift_enforcement():
    """Verify that anomaly.py contains strictly zero float division (/) and zero float conversions."""
    anomaly_path = Path(__file__).resolve().parent.parent / "src" / "ironledger" / "governance" / "anomaly.py"
    assert anomaly_path.is_file()

    tree = ast.parse(anomaly_path.read_text(encoding="utf-8"), filename=str(anomaly_path))

    class FloatAstScanner(ast.NodeVisitor):
        def __init__(self):
            self.violations: list[str] = []

        def visit_BinOp(self, node: ast.BinOp):
            if isinstance(node.op, ast.Div):
                self.violations.append(f"Line {node.lineno}: Prohibited float division operator '/'")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("float", "Decimal"):
                self.violations.append(f"Line {node.lineno}: Prohibited float/Decimal call '{node.func.id}()'")
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant):
            if isinstance(node.value, float):
                self.violations.append(f"Line {node.lineno}: Prohibited float literal '{node.value}'")
            self.generic_visit(node)

    scanner = FloatAstScanner()
    scanner.visit(tree)
    assert not scanner.violations, f"Float violations found in anomaly.py: {scanner.violations}"


def test_detect_duplicate_charges():
    txs = [
        NormalizedTransaction(
            id="tx1",
            ledger_id="led_1",
            timestamp_utc="2026-06-01T10:00:00Z",
            amount_cents=5000,
            currency="USD",
            account_id="acc_checking",
            payee="Acme Corp",
        ),
        NormalizedTransaction(
            id="tx2",
            ledger_id="led_1",
            timestamp_utc="2026-06-01T10:05:00Z",
            amount_cents=5000,
            currency="USD",
            account_id="acc_checking",
            payee="Acme Corp",
        ),
        NormalizedTransaction(
            id="tx3",
            ledger_id="led_1",
            timestamp_utc="2026-06-01T10:10:00Z",
            amount_cents=2500,
            currency="USD",
            account_id="acc_checking",
            payee="Other",
        ),
    ]

    findings = detect_duplicate_charges(txs, window_seconds=600)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_type == "DUPLICATE_CHARGE"
    assert f.staged_transaction_id == "tx2"
    assert f.details["matched_tx_id"] == "tx1"


def test_detect_velocity_spikes():
    txs = [
        NormalizedTransaction(
            id=f"tx_{i}",
            ledger_id="led_1",
            timestamp_utc=f"2026-06-01T10:0{i}:00Z",
            amount_cents=10000,
            currency="USD",
            account_id="acc_checking",
            payee="Coffee Shop",
        )
        for i in range(6)
    ]

    findings = detect_velocity_spikes(txs, window_seconds=3600, max_count=4)
    assert len(findings) >= 1
    assert any(f.rule_type == "VELOCITY_SPIKE" for f in findings)


def test_detect_rational_outliers_exact_math():
    # 9 normal transactions of $10.00 (1000 cents) and 1 extreme outlier of $5,000.00 (500000 cents)
    txs = [
        NormalizedTransaction(
            id=f"tx_norm_{i}",
            ledger_id="led_1",
            timestamp_utc="2026-06-01T12:00:00Z",
            amount_cents=1000,
            currency="USD",
            account_id="acc_checking",
            payee="Vendor",
        )
        for i in range(9)
    ]
    txs.append(
        NormalizedTransaction(
            id="tx_outlier",
            ledger_id="led_1",
            timestamp_utc="2026-06-01T12:05:00Z",
            amount_cents=500000,
            currency="USD",
            account_id="acc_checking",
            payee="Luxury Vendor",
        )
    )

    findings = detect_rational_outliers(txs, k_numerator=2, k_denominator=1)
    assert len(findings) == 1
    assert findings[0].staged_transaction_id == "tx_outlier"
    assert findings[0].rule_type == "RATIONAL_OUTLIER"


def test_detect_unusual_payees():
    history = [
        NormalizedTransaction(
            id=f"hist_{i}",
            ledger_id="led_1",
            timestamp_utc="2026-05-01T12:00:00Z",
            amount_cents=1000,
            currency="USD",
            account_id="acc_checking",
            payee="Daily Grocery",
        )
        for i in range(25)
    ]
    current = [
        NormalizedTransaction(
            id="tx_rare",
            ledger_id="led_1",
            timestamp_utc="2026-06-01T12:00:00Z",
            amount_cents=2000,
            currency="USD",
            account_id="acc_checking",
            payee="Obscure Foreign Shop",
        )
    ]

    findings = detect_unusual_payees(current, history_transactions=history, min_history_size=10)
    assert len(findings) == 1
    assert findings[0].staged_transaction_id == "tx_rare"
    assert findings[0].rule_type == "UNUSUAL_PAYEE"


def test_scan_and_resolve_lifecycle(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO ledgers (ledger_id, name, base_currency) VALUES (?, ?, ?)",
        ("led_anom", "Anomaly Ledger", "USD"),
    )
    conn.commit()

    txs = [
        NormalizedTransaction(
            id="tx_a",
            ledger_id="led_anom",
            timestamp_utc="2026-06-01T10:00:00Z",
            amount_cents=1000,
            currency="USD",
            account_id="acc_main",
            payee="Shop",
        ),
        NormalizedTransaction(
            id="tx_b",
            ledger_id="led_anom",
            timestamp_utc="2026-06-01T10:01:00Z",
            amount_cents=1000,
            currency="USD",
            account_id="acc_main",
            payee="Shop",
        ),
    ]

    findings = scan_and_persist_anomalies(conn, "led_anom", txs)
    conn.commit()
    assert len(findings) >= 1
    flag_id = findings[0].flag_id

    # Resolve flag
    success = resolve_anomaly_flag(
        conn=conn,
        ledger_id="led_anom",
        flag_id=flag_id,
        resolution_status="CONFIRMED_FRAUD",
        actor="lead_auditor",
        reason="Verified double charge with merchant",
    )
    conn.commit()
    assert success is True

    # Check governance audit event was emitted
    cursor = conn.cursor()
    cursor.execute(
        "SELECT actor, action, target FROM governance_audit_events WHERE ledger_id = ?",
        ("led_anom",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "lead_auditor"
    assert row[1] == "RESOLVE_ANOMALY_FLAG"
    assert row[2] == f"anomaly_flag:{flag_id}"

    # Repeated resolution should fail closed
    with pytest.raises(AnomalyEngineError, match="already resolved"):
        resolve_anomaly_flag(
            conn=conn,
            ledger_id="led_anom",
            flag_id=flag_id,
            resolution_status="DISMISSED",
            actor="other_actor",
        )
