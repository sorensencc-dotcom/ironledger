"""Phase 1 task 2: migration runner.

A fresh database applies migrations in order and reports the expected schema
version. No migration applies twice. An interrupted migration leaves a
recoverable state with no partially accepted schema version.
"""

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect

CORE_TABLES = {
    "source_documents",
    "source_records",
    "fitid_trust_records",
    "staged_transactions",
    "compile_runs",
    "ledger_entries",
    "ledger_postings",
    "audit_events",
}


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {name for (name,) in rows}


def test_packaged_migrations_are_a_gapless_sequence():
    discovered = migrations.discover_migrations()
    assert [m.version for m in discovered] == list(range(1, len(discovered) + 1))


def test_fresh_apply_reaches_expected_version_and_tables():
    conn = connect(":memory:")
    expected = len(migrations.discover_migrations())
    version = migrations.migrate(conn)
    assert version == expected
    assert version >= 2
    assert CORE_TABLES.issubset(table_names(conn))


def test_reapply_is_a_noop():
    conn = connect(":memory:")
    first = migrations.migrate(conn)
    applied_before = migrations.applied_migrations(conn)
    second = migrations.migrate(conn)
    assert first == second
    assert migrations.applied_migrations(conn) == applied_before


def test_interrupted_migration_does_not_advance_version(tmp_path):
    (tmp_path / "0001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8"
    )
    (tmp_path / "0002_broken.sql").write_text(
        "CREATE TABLE beta (id INTEGER PRIMARY KEY) STRICT;\n"
        "THIS IS NOT VALID SQL;",
        encoding="utf-8",
    )
    conn = connect(":memory:")

    with pytest.raises(sqlite3.OperationalError):
        migrations.migrate(conn, directory=tmp_path)

    assert migrations.current_version(conn) == 1
    assert "alpha" in table_names(conn)
    assert "beta" not in table_names(conn)  # the broken file rolled back whole


def test_interrupted_migration_is_recoverable_after_fix(tmp_path):
    (tmp_path / "0001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8"
    )
    broken = tmp_path / "0002_second.sql"
    broken.write_text("CREATE TABLE beta (id INTEGER PRIMARY KEY) STRICT;\nBOOM;", encoding="utf-8")
    conn = connect(":memory:")
    with pytest.raises(sqlite3.OperationalError):
        migrations.migrate(conn, directory=tmp_path)
    assert migrations.current_version(conn) == 1

    broken.write_text("CREATE TABLE beta (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8")
    version = migrations.migrate(conn, directory=tmp_path)
    assert version == 2
    assert {"alpha", "beta"}.issubset(table_names(conn))


def test_checksum_change_after_apply_is_rejected(tmp_path):
    migration = tmp_path / "0001_first.sql"
    migration.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8")
    conn = connect(":memory:")
    assert migrations.migrate(conn, directory=tmp_path) == 1

    migration.write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY, extra TEXT) STRICT;", encoding="utf-8"
    )
    with pytest.raises(migrations.ChecksumMismatch):
        migrations.migrate(conn, directory=tmp_path)


def test_version_gap_is_rejected(tmp_path):
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8")
    (tmp_path / "0003_third.sql").write_text("CREATE TABLE c (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8")
    conn = connect(":memory:")
    with pytest.raises(migrations.MigrationError):
        migrations.migrate(conn, directory=tmp_path)


def test_schema_migrations_row_recorded_with_checksum():
    conn = connect(":memory:")
    migrations.migrate(conn)
    rows = migrations.applied_migrations(conn)
    assert len(rows) == len(migrations.discover_migrations())
    for version, name, checksum in rows:
        assert version >= 1
        assert len(name) > 0
        assert len(checksum) == 64

