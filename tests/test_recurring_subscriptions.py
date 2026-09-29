"""Tests for subscription intelligence, cadence analysis, and price-jump detection."""

from __future__ import annotations

import ast
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from ironledger.analytics.subscriptions import (
    calculate_normalized_monthly_minor,
    get_recurring_subscriptions,
    project_next_billing_date,
)
from ironledger.db.migrations import migrate_governed
from ironledger.mcp.tools import call_tool, list_tools
from ironledger.web.app import create_app


def test_subscriptions_ast_invariants():
    """Verify zero ast.Div and zero import beancount in the subscriptions engine."""
    source_path = Path("src/ironledger/analytics/subscriptions.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        assert not isinstance(node, ast.Div), "Floating-point division (ast.Div) forbidden in subscriptions.py"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for mod in names:
                assert "beancount" not in mod, f"Forbidden import of beancount detected: {mod}"


def test_normalized_monthly_minor_math():
    """Verify exact integer monthly normalization across cadences."""
    # Weekly: ($10.00 = 1000 minor units) -> 1000 * 52 / 12 = 4333.33 -> 4333 integer cents
    assert calculate_normalized_monthly_minor(1000, "WEEKLY") == 4333
    # Bi-weekly: ($100.00 = 10000 minor units) -> 10000 * 26 / 12 = 21666.66 -> 21667 integer cents
    assert calculate_normalized_monthly_minor(10000, "BIWEEKLY") == 21667
    # Monthly: ($15.99 = 1599 minor units) -> 1599
    assert calculate_normalized_monthly_minor(1599, "MONTHLY") == 1599
    # Quarterly: ($30.00 = 3000 minor units) -> 1000
    assert calculate_normalized_monthly_minor(3000, "QUARTERLY") == 1000
    # Annual: ($120.00 = 12000 minor units) -> 1000
    assert calculate_normalized_monthly_minor(12000, "ANNUAL") == 1000


def test_project_next_billing_date():
    """Verify next billing date projection across intervals."""
    assert project_next_billing_date("2026-01-15", "WEEKLY") == "2026-01-22"
    assert project_next_billing_date("2026-01-15", "BIWEEKLY") == "2026-01-29"
    assert project_next_billing_date("2026-01-15", "MONTHLY") == "2026-02-15"
    assert project_next_billing_date("2026-01-31", "MONTHLY") == "2026-02-28"
    assert project_next_billing_date("2026-01-15", "QUARTERLY") == "2026-04-15"
    assert project_next_billing_date("2026-01-15", "ANNUAL") == "2027-01-15"


def _seed_subscription_database(conn: sqlite3.Connection) -> None:
    """Helper to seed sample transactions for subscription analysis."""
    migrate_governed(conn)
    conn.execute("PRAGMA foreign_keys = OFF")

    sha_a = "a" * 64
    sha_b = "b" * 64
    sha_c = "c" * 64
    sha_d = "d" * 64
    sha_e = "e" * 64
    sha_f = "f" * 64

    # Seed source document & record
    conn.execute(f"""
        INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc, ledger_id)
        VALUES ('doc-1', 'text/csv', 'utf-8', 'Test', '2026-01-01T00:00:00Z', '{sha_a}', 'ref1', '2026-01-01T00:00:00Z', 'default')
    """)
    conn.execute(f"""
        INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc, ledger_id)
        VALUES ('rec-1', 'doc-1', 0, 'payload', '{sha_b}', '2026-01-01T00:00:00Z', 'default')
    """)

    import hashlib

    # Seed recurring Netflix transactions (Monthly with price jump)
    netflix_txs = [
        ("st-n1", "le-n1", "lp-n1", "2026-01-15", "Netflix", 1599),
        ("st-n2", "le-n2", "lp-n2", "2026-02-15", "Netflix", 1599),
        ("st-n3", "le-n3", "lp-n3", "2026-03-15", "Netflix", 1999), # Price jump
    ]

    for st_id, le_id, lp_id, dt, payee, amt in netflix_txs:
        fp_st = hashlib.sha256(st_id.encode()).hexdigest()
        fp_lp = hashlib.sha256(lp_id.encode()).hexdigest()
        conn.execute(f"""
            INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, ledger_id)
            VALUES ('{st_id}', 'rec-1', 'approved', '{dt}', '{payee}', 'Monthly Subscription', 1, 'sha256_fallback', '{fp_st}', '{dt}T00:00:00Z', 'default')
        """)
        conn.execute(f"""
            INSERT INTO ledger_entries (ledger_entry_id, staged_transaction_id, entry_date, flag, payee, narration, created_at_utc)
            VALUES ('{le_id}', '{st_id}', '{dt}', '*', '{payee}', 'Monthly Subscription', '{dt}T00:00:00Z')
        """)
        conn.execute(f"""
            INSERT INTO ledger_postings (ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, currency, minor_unit_scale, identity_algo_version, identity_method, identity_fingerprint, created_at_utc)
            VALUES ('{lp_id}', '{le_id}', 'rec-1', 'Expenses:Entertainment:Streaming', {amt}, 'USD', 2, 1, 'sha256_fallback', '{fp_lp}', '{dt}T00:00:00Z')
        """)

    # Seed recurring Gym membership (Weekly)
    gym_txs = [
        ("st-g1", "le-g1", "lp-g1", "2026-03-01", "FitGym", 2500),
        ("st-g2", "le-g2", "lp-g2", "2026-03-08", "FitGym", 2500),
        ("st-g3", "le-g3", "lp-g3", "2026-03-15", "FitGym", 2500),
    ]

    for st_id, le_id, lp_id, dt, payee, amt in gym_txs:
        fp_st = hashlib.sha256(st_id.encode()).hexdigest()
        fp_lp = hashlib.sha256(lp_id.encode()).hexdigest()
        conn.execute(f"""
            INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, ledger_id)
            VALUES ('{st_id}', 'rec-1', 'approved', '{dt}', '{payee}', 'Weekly Membership', 1, 'sha256_fallback', '{fp_st}', '{dt}T00:00:00Z', 'default')
        """)
        conn.execute(f"""
            INSERT INTO ledger_entries (ledger_entry_id, staged_transaction_id, entry_date, flag, payee, narration, created_at_utc)
            VALUES ('{le_id}', '{st_id}', '{dt}', '*', '{payee}', 'Weekly Membership', '{dt}T00:00:00Z')
        """)
        conn.execute(f"""
            INSERT INTO ledger_postings (ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, currency, minor_unit_scale, identity_algo_version, identity_method, identity_fingerprint, created_at_utc)
            VALUES ('{lp_id}', '{le_id}', 'rec-1', 'Expenses:Health:Fitness', {amt}, 'USD', 2, 1, 'sha256_fallback', '{fp_lp}', '{dt}T00:00:00Z')
        """)

    conn.commit()


def test_recurring_subscriptions_query():
    """Verify subscription detection, cadence classification, and price jump flagging."""
    conn = sqlite3.connect(":memory:")
    _seed_subscription_database(conn)

    data = get_recurring_subscriptions(conn, ledger_id="default")
    assert data["subscription_count"] == 2
    assert data["price_jump_count"] == 1

    netflix = next(s for s in data["subscriptions"] if s["display_payee"] == "Netflix")
    assert netflix["cadence"] == "MONTHLY"
    assert netflix["last_amount_minor"] == 1999
    assert netflix["prev_amount_minor"] == 1599
    assert netflix["is_price_jump"] is True
    assert netflix["price_jump_minor"] == 400
    assert netflix["projected_next_date"] == "2026-04-15"

    gym = next(s for s in data["subscriptions"] if s["display_payee"] == "FitGym")
    assert gym["cadence"] == "WEEKLY"
    assert gym["last_amount_minor"] == 2500
    assert gym["is_price_jump"] is False
    assert gym["projected_next_date"] == "2026-03-22"

    # FitGym monthly: (2500 * 52 + 6) // 12 = 10833
    # Netflix monthly: 1999
    # Total monthly overhead: 10833 + 1999 = 12832
    assert data["total_monthly_overhead_minor"] == 12832


def test_web_analytics_subscriptions_endpoints(tmp_path):
    """Verify FastAPI analytics endpoints for subscriptions."""
    db_path = tmp_path / "test_subs.db"
    conn = sqlite3.connect(str(db_path))
    _seed_subscription_database(conn)
    conn.close()

    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    res = client.get("/api/analytics/subscriptions?ledger_id=default")
    assert res.status_code == 200
    payload = res.json()
    assert payload["subscription_count"] == 2
    assert payload["price_jump_count"] == 1

    jump_res = client.get("/api/analytics/subscriptions/price-jumps?ledger_id=default")
    assert jump_res.status_code == 200
    jumps = jump_res.json()
    assert len(jumps) == 1
    assert jumps[0]["display_payee"] == "Netflix"
    assert jumps[0]["price_jump_minor"] == 400


def test_mcp_subscription_tool(tmp_path: Path):
    """Verify MCP tool registry and dispatch for get_recurring_subscriptions."""
    tools = list_tools(include_analytics=True)
    tool_names = [t["name"] for t in tools]
    assert "get_recurring_subscriptions" in tool_names

    from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger
    from ironledger.project.activate import rebuild_projection
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir, "run-1")

    conn = sqlite3.connect(str(db_path))
    _seed_subscription_database(conn)
    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()

    res = call_tool(
        "get_recurring_subscriptions",
        {"ledger_id": "default"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=str(db_path),
    )
    assert res["isError"] is False
    import json
    data = json.loads(res["content"][0]["text"])
    assert data["subscription_count"] == 2
    assert data["price_jump_count"] == 1


