"""Phase 5 / Meta-Ledger: migration 0006 adds the append-only mutation_events table."""

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


def test_reaches_version_six(db: sqlite3.Connection):
    assert migrations.current_version(db) >= 6


def test_mutation_events_table_present_and_accepts_valid_row(db: sqlite3.Connection):
    db.execute(
        "INSERT INTO mutation_events (seq, mutation_id, ts_utc, operator_session, action, "
        " staged_count, rules_applied, rules_created, sha256_before, sha256_after, "
        " prev_mutation_hash, mutation_hash) "
        "VALUES (1, 'mut_test_1', '2026-09-09T12:00:00Z', 'sess_1', 'compile', 5, 4, 1, "
        f"'{'0'*64}', '{'1'*64}', '{'0'*64}', '{'2'*64}')"
    )
    db.commit()
    row = db.execute(
        "SELECT seq, mutation_id, action, staged_count FROM mutation_events WHERE seq = 1"
    ).fetchone()
    assert row == (1, "mut_test_1", "compile", 5)


def test_mutation_0006_checksum_frozen():
    """Verify that the migration runner enforces checksum immutability for 0006."""
    with tempfile.TemporaryDirectory() as tmpdir:
        schema_dir = Path(tmpdir) / "schema"
        schema_dir.mkdir()
        source_dir = Path(__file__).parent.parent / "src" / "ironledger" / "db" / "schema"
        for source in source_dir.glob("*.sql"):
            (schema_dir / source.name).write_bytes(source.read_bytes())
        db_path = Path(tmpdir) / "test.db"
        conn_first = connect(str(db_path))
        migrations.migrate(conn_first, directory=schema_dir)
        assert migrations.current_version(conn_first) >= 6
        conn_first.close()

        target = schema_dir / "0006_mutation_events.sql"
        target.write_bytes(target.read_bytes() + b"\n-- mutated comment\n")
        conn_second = connect(str(db_path))
        with pytest.raises(migrations.ChecksumMismatch, match="changed on disk"):
            migrations.migrate(conn_second, directory=schema_dir)
        conn_second.close()
