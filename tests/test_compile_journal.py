"""Tests for compile run lifecycle and append-only journal persistence."""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.journal import (
    start_compile_run,
    append_compile_journal,
    finish_compile_run,
    fail_compile_run,
    get_active_started_run,
    get_latest_successful_run,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_compile_run_lifecycle_and_journal_sequence(db: sqlite3.Connection):
    run_id = "run-100"
    start_compile_run(
        db,
        compile_run_id=run_id,
        beancount_version="3.0.0",
        compiler_version="0.1.0",
        input_hash="a" * 64,
        intended_output_hash="b" * 64,
        now_utc="2026-09-06T12:00:00Z",
    )

    started_run = get_active_started_run(db)
    assert started_run is not None
    assert started_run["compile_run_id"] == run_id

    seq1 = append_compile_journal(db, run_id, "bean_checked", now_utc="2026-09-06T12:00:01Z")
    assert seq1 == 2  # seq 1 was 'started' in start_compile_run

    finish_compile_run(
        db,
        compile_run_id=run_id,
        actual_output_hash="b" * 64,
        now_utc="2026-09-06T12:00:02Z",
    )

    assert get_active_started_run(db) is None
    latest = get_latest_successful_run(db)
    assert latest is not None
    assert latest["compile_run_id"] == run_id
    assert latest["status"] == "succeeded"


def test_fail_compile_run_records_failure(db: sqlite3.Connection):
    run_id = "run-fail"
    start_compile_run(
        db,
        compile_run_id=run_id,
        beancount_version="3.0.0",
        compiler_version="0.1.0",
        input_hash="a" * 64,
        intended_output_hash="b" * 64,
    )
    fail_compile_run(db, run_id, detail="bean-check exited 1")
    assert get_active_started_run(db) is None
    row = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()
    assert row[0] == "failed"


def test_deterministic_lookup_with_same_timestamp_tiebreaker(db: sqlite3.Connection):
    """Verify rowid tiebreaker determinism when two runs share a timestamp."""
    # Two runs with identical start timestamp (same second)
    run_id_1 = "run-ts-1"
    run_id_2 = "run-ts-2"
    ts = "2026-09-06T12:00:00Z"

    # Insert first run
    start_compile_run(
        db,
        compile_run_id=run_id_1,
        beancount_version="3.0.0",
        compiler_version="0.1.0",
        input_hash="a" * 64,
        intended_output_hash="b" * 64,
        now_utc=ts,
    )

    # Insert second run with same timestamp
    start_compile_run(
        db,
        compile_run_id=run_id_2,
        beancount_version="3.0.0",
        compiler_version="0.1.0",
        input_hash="c" * 64,
        intended_output_hash="d" * 64,
        now_utc=ts,
    )

    # get_active_started_run should return second-inserted (higher rowid)
    active = get_active_started_run(db)
    assert active is not None
    assert active["compile_run_id"] == run_id_2

    # Finish both with same timestamp
    finish_compile_run(
        db,
        compile_run_id=run_id_1,
        actual_output_hash="b" * 64,
        now_utc=ts,
    )
    finish_compile_run(
        db,
        compile_run_id=run_id_2,
        actual_output_hash="d" * 64,
        now_utc=ts,
    )

    # get_latest_successful_run should return second-inserted (higher rowid)
    latest = get_latest_successful_run(db)
    assert latest is not None
    assert latest["compile_run_id"] == run_id_2


def test_fail_compile_run_only_affects_started_runs(db: sqlite3.Connection):
    """#9: fail_compile_run must not clobber a run that already succeeded."""
    run_id = "run-guard"
    start_compile_run(
        db, compile_run_id=run_id, beancount_version="3.0.0", compiler_version="0.1.0",
        input_hash="a" * 64, intended_output_hash="b" * 64, now_utc="2026-09-06T12:00:00Z",
    )
    finish_compile_run(
        db, compile_run_id=run_id, actual_output_hash="b" * 64, now_utc="2026-09-06T12:00:01Z",
    )

    fail_compile_run(db, run_id, detail="late failure", now_utc="2026-09-06T12:00:02Z")

    status = db.execute(
        "SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)
    ).fetchone()[0]
    assert status == "succeeded"
