"""Phase 3: migration 0005 adds the append-only compile_journal table."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_compile_run(conn: sqlite3.Connection, run_id: str = "run-1") -> str:
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, status, started_at_utc, recovery_state) "
        f"VALUES ('{run_id}', '3.0.0', '0.1.0', '{'a'*64}', '{'b'*64}', 'started', "
        " '2026-09-06T12:00:00Z', 'none')"
    )
    conn.commit()
    return run_id


def test_reaches_version_five(db: sqlite3.Connection):
    assert migrations.current_version(db) >= 5


def test_compile_journal_table_present_and_accepts_valid_row(db: sqlite3.Connection):
    run_id = _seed_compile_run(db)
    db.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        f"VALUES (1, '{run_id}', 'started', '2026-09-06T12:00:00Z', 'initial start')"
    )
    db.commit()
    row = db.execute(
        "SELECT seq, compile_run_id, state, ts_utc, detail FROM compile_journal WHERE seq = 1"
    ).fetchone()
    assert row == (1, run_id, "started", "2026-09-06T12:00:00Z", "initial start")


def test_compile_journal_triggers_prevent_update_and_delete(db: sqlite3.Connection):
    run_id = _seed_compile_run(db)
    db.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        f"VALUES (1, '{run_id}', 'started', '2026-09-06T12:00:00Z', '')"
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="compile_journal is append-only: UPDATE is forbidden"):
        db.execute("UPDATE compile_journal SET state = 'succeeded' WHERE seq = 1")

    with pytest.raises(sqlite3.IntegrityError, match="compile_journal is append-only: DELETE is forbidden"):
        db.execute("DELETE FROM compile_journal WHERE seq = 1")


def test_migration_0005_checksum_frozen():
    """Verify that the migration runner enforces checksum immutability for 0005."""
    with tempfile.TemporaryDirectory() as tmpdir:
        schema_dir = Path(tmpdir) / "schema"
        schema_dir.mkdir()
        source_dir = Path(__file__).parent.parent / "src" / "ironledger" / "db" / "schema"
        for source in source_dir.glob("*.sql"):
            (schema_dir / source.name).write_bytes(source.read_bytes())
        db_path = Path(tmpdir) / "test.db"
        conn_first = connect(str(db_path))
        migrations.migrate(conn_first, directory=schema_dir)
        assert migrations.current_version(conn_first) >= 5
        conn_first.close()
        target = schema_dir / "0005_compile_journal.sql"
        target.write_bytes(target.read_bytes() + b"\n-- mutated comment\n")
        conn_second = connect(str(db_path))
        with pytest.raises(migrations.ChecksumMismatch, match="changed on disk"):
            migrations.migrate(conn_second, directory=schema_dir)
        conn_second.close()
