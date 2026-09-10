"""Tests for Projection Freshness & SLA Monitoring (Task 6.3)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pytest

from ironledger.governance.freshness import (
    FreshnessTier,
    ProjectionFreshnessResult,
    evaluate_projection_freshness,
    check_projection_db_freshness,
)
from ironledger.governance.mutations import compute_canonical_ledger_manifest_hash
import ironledger.governance as gov


def test_freshness_latency_tiers():
    h = "a" * 64
    # Fresh: < 5s and hash match
    res1 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:03Z")
    assert res1.status == FreshnessTier.FRESH
    assert res1.latency_seconds == 3.0
    assert res1.source_hash_match is True
    assert res1.ledger_source_sha256 == h
    assert res1.projection_source_sha256 == h
    assert res1.built_at_utc == "2026-09-09T20:00:00Z"

    # Boundary test: exactly 4.99s -> FRESH
    res_b1 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:04.990Z")
    assert res_b1.status == FreshnessTier.FRESH

    # Boundary test: exactly 5.0s -> STALE
    res_b2 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:05Z")
    assert res_b2.status == FreshnessTier.STALE
    assert res_b2.latency_seconds == 5.0

    # Stale: 5.0s <= delta_t <= 30.0s and hash match
    res2 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:15Z")
    assert res2.status == FreshnessTier.STALE
    assert res2.latency_seconds == 15.0
    assert res2.source_hash_match is True

    # Boundary test: exactly 30.0s -> STALE
    res_b3 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:30Z")
    assert res_b3.status == FreshnessTier.STALE
    assert res_b3.latency_seconds == 30.0

    # Critical: > 30.0s
    res3 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:30.010Z")
    assert res3.status == FreshnessTier.CRITICAL
    assert res3.latency_seconds == 30.01

    res4 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:45Z")
    assert res4.status == FreshnessTier.CRITICAL
    assert res4.latency_seconds == 45.0
    assert res4.source_hash_match is True


def test_unidirectional_latency_and_clock_rollback():
    h = "a" * 64
    # Clock rollback: built timestamp in future relative to now_utc
    # delta_t = max(0.0, current_utc - built_at_utc) -> clamped to 0.0
    res = evaluate_projection_freshness(
        h,
        h,
        built_at_utc="2026-09-09T20:05:00Z",
        now_utc="2026-09-09T20:00:00Z",
    )
    assert res.latency_seconds == 0.0
    assert res.status == FreshnessTier.FRESH
    assert res.source_hash_match is True


def test_hash_mismatch_forces_critical():
    # Even with 0s latency, hash divergence independently forces CRITICAL
    res1 = evaluate_projection_freshness(
        "a" * 64,
        "b" * 64,
        "2026-09-09T20:00:00Z",
        "2026-09-09T20:00:00Z",
    )
    assert res1.status == FreshnessTier.CRITICAL
    assert res1.source_hash_match is False
    assert res1.latency_seconds == 0.0

    # Hash mismatch with 10s latency
    res2 = evaluate_projection_freshness(
        "a" * 64,
        "b" * 64,
        "2026-09-09T20:00:00Z",
        "2026-09-09T20:00:10Z",
    )
    assert res2.status == FreshnessTier.CRITICAL
    assert res2.source_hash_match is False


def test_case_insensitive_hash_comparison():
    h_lower = "abcdef0123456789" * 4
    h_upper = h_lower.upper()
    res = evaluate_projection_freshness(
        h_lower,
        h_upper,
        "2026-09-09T20:00:00Z",
        "2026-09-09T20:00:02Z",
    )
    assert res.source_hash_match is True
    assert res.status == FreshnessTier.FRESH


def test_default_now_utc():
    h = "c" * 64
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = evaluate_projection_freshness(h, h, built_at_utc=now)
    assert res.status == FreshnessTier.FRESH
    assert res.latency_seconds >= 0.0
    assert res.source_hash_match is True


def test_check_projection_db_freshness_with_live_ledger(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    (ledger_dir / "2026.beancount").write_text(
        '2026-01-01 open Assets:Bank:Checking USD\n'
        '2026-01-02 * "Opening balance"\n'
        '  Assets:Bank:Checking  100 USD\n'
        '  Equity:Opening-Balances\n',
        encoding="utf-8",
    )

    ledger_hash = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert len(ledger_hash) == 64

    # Create SQLite projection db with projection_metadata table
    proj_db = tmp_path / "projection.db"
    with sqlite3.connect(str(proj_db)) as conn:
        conn.execute(
            """
            CREATE TABLE projection_metadata (
                built_at_utc TEXT NOT NULL,
                source_sha256 TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO projection_metadata (built_at_utc, source_sha256) VALUES (?, ?)",
            ("2026-09-09T20:00:00Z", ledger_hash),
        )
        conn.commit()

    # 1. Fresh case: now is 2s later
    res_fresh = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T20:00:02Z",
    )
    assert res_fresh.status == FreshnessTier.FRESH
    assert res_fresh.latency_seconds == 2.0
    assert res_fresh.source_hash_match is True
    assert res_fresh.ledger_source_sha256 == ledger_hash
    assert res_fresh.projection_source_sha256 == ledger_hash
    assert res_fresh.built_at_utc == "2026-09-09T20:00:00Z"

    # 2. Stale case: now is 15s later
    res_stale = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T20:00:15Z",
    )
    assert res_stale.status == FreshnessTier.STALE
    assert res_stale.latency_seconds == 15.0
    assert res_stale.source_hash_match is True

    # 3. Critical case: now is 40s later
    res_crit_time = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T20:00:40Z",
    )
    assert res_crit_time.status == FreshnessTier.CRITICAL
    assert res_crit_time.latency_seconds == 40.0
    assert res_crit_time.source_hash_match is True

    # 4. Hash divergence case: ledger modified on disk
    (ledger_dir / "2026.beancount").write_text(
        '2026-01-01 open Assets:Bank:Checking USD\n'
        '2026-01-02 * "Modified entry"\n'
        '  Assets:Bank:Checking  200 USD\n'
        '  Equity:Opening-Balances\n',
        encoding="utf-8",
    )
    res_crit_hash = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T20:00:02Z",
    )
    assert res_crit_hash.status == FreshnessTier.CRITICAL
    assert res_crit_hash.source_hash_match is False
    assert res_crit_hash.latency_seconds == 2.0
    assert res_crit_hash.ledger_source_sha256 != ledger_hash


def test_check_projection_db_freshness_projection_meta_table(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    (ledger_dir / "2026.beancount").write_text("2026-01-01 open Assets:Bank USD\n", encoding="utf-8")
    ledger_hash = compute_canonical_ledger_manifest_hash(ledger_dir)

    # Test compatibility with projection_meta table and ledger_output_hash column
    proj_db = tmp_path / "projection.sqlite"
    with sqlite3.connect(str(proj_db)) as conn:
        conn.execute(
            """
            CREATE TABLE projection_meta (
                singleton INTEGER PRIMARY KEY,
                built_at_utc TEXT NOT NULL,
                ledger_output_hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO projection_meta (singleton, built_at_utc, ledger_output_hash) VALUES (1, ?, ?)",
            ("2026-09-09T20:00:00Z", ledger_hash),
        )
        conn.commit()

    res = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T20:00:01Z",
    )
    assert res.status == FreshnessTier.FRESH
    assert res.source_hash_match is True
    assert res.projection_source_sha256 == ledger_hash


def test_check_projection_db_errors(tmp_path: Path):
    valid_ledger = tmp_path / "ledger"
    valid_ledger.mkdir()
    (valid_ledger / "main.beancount").write_text("2026-01-01 open Assets:Cash USD\n")

    # Missing projection DB file
    with pytest.raises(FileNotFoundError):
        check_projection_db_freshness(tmp_path / "nonexistent.db", valid_ledger)

    # Missing ledger directory
    existing_db = tmp_path / "empty.db"
    with sqlite3.connect(str(existing_db)) as conn:
        conn.execute("CREATE TABLE t (x INT)")
    with pytest.raises(FileNotFoundError):
        check_projection_db_freshness(existing_db, tmp_path / "nonexistent_ledger")

    # Missing metadata table
    with pytest.raises(sqlite3.OperationalError):
        check_projection_db_freshness(existing_db, valid_ledger)


def test_governance_exports():
    assert hasattr(gov, "FreshnessTier")
    assert hasattr(gov, "ProjectionFreshnessResult")
    assert hasattr(gov, "evaluate_projection_freshness")
    assert hasattr(gov, "check_projection_db_freshness")
