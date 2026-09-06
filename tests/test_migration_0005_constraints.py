"""Exhaustive constraint and trigger tests for compile_journal table."""

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


def _seed_run(conn: sqlite3.Connection, run_id: str = "run-1") -> str:
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, status, started_at_utc, recovery_state) "
        f"VALUES ('{run_id}', '3.0.0', '0.1.0', '{'a'*64}', '{'b'*64}', 'started', "
        " '2026-09-06T12:00:00Z', 'none')"
    )
    conn.commit()
    return run_id


@pytest.mark.parametrize("valid_state", [
    "started", "bean_checked", "replaced", "succeeded", "failed", "recovered", "refused"
])
def test_all_valid_states_accepted(db: sqlite3.Connection, valid_state: str):
    run_id = _seed_run(db)
    db.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        f"VALUES (1, '{run_id}', '{valid_state}', '2026-09-06T12:00:00Z', '')"
    )
    db.commit()
    assert db.execute("SELECT state FROM compile_journal WHERE seq = 1").fetchone()[0] == valid_state


def test_invalid_state_rejected(db: sqlite3.Connection):
    run_id = _seed_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            f"VALUES (1, '{run_id}', 'invalid_state', '2026-09-06T12:00:00Z', '')"
        )


def test_foreign_key_to_compile_runs_enforced(db: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            "VALUES (1, 'non-existent-run', 'started', '2026-09-06T12:00:00Z', '')"
        )


def test_seq_less_than_one_rejected(db: sqlite3.Connection):
    run_id = _seed_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            f"VALUES (0, '{run_id}', 'started', '2026-09-06T12:00:00Z', '')"
        )


def test_timestamp_format_glob_enforced(db: sqlite3.Connection):
    run_id = _seed_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            f"VALUES (1, '{run_id}', 'started', '2026-09-06 12:00:00', '')"
        )
