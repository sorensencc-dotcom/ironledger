"""Tests for IronLedger forward-only governed migration engine."""

import sqlite3
from pathlib import Path

import pytest

from ironledger.db.connection import connect
from ironledger.governance.migrations import (
    ChecksumMismatch,
    ForeignKeyViolationError,
    Migration,
    MigrationError,
    applied_migrations,
    current_version,
    discover_migrations,
    migrate_governed,
    verify_schema_checksums,
)


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {name for (name,) in rows}


def test_packaged_migrations_discovery():
    migrations = discover_migrations()
    assert len(migrations) >= 6
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    for m in migrations:
        assert isinstance(m, Migration)
        assert len(m.checksum) == 64
        assert len(m.name) > 0


def test_verify_schema_checksums_fresh_db():
    conn = connect(":memory:")
    assert verify_schema_checksums(conn) is True


def test_verify_schema_checksums_applied_match():
    conn = connect(":memory:")
    version = migrate_governed(conn)
    assert version >= 6
    assert verify_schema_checksums(conn) is True


def test_verify_schema_checksums_detects_disk_tamper(tmp_path: Path):
    mig1 = tmp_path / "0001_initial.sql"
    mig1.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8")
    conn = connect(":memory:")
    assert migrate_governed(conn, directory=tmp_path) == 1

    # Tamper with file on disk
    mig1.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY, extra TEXT) STRICT;", encoding="utf-8")
    with pytest.raises(ChecksumMismatch, match="changed on disk after being applied"):
        verify_schema_checksums(conn, directory=tmp_path)


def test_verify_schema_checksums_detects_missing_file(tmp_path: Path):
    mig1 = tmp_path / "0001_initial.sql"
    mig1.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8")
    conn = connect(":memory:")
    assert migrate_governed(conn, directory=tmp_path) == 1

    # Delete file from disk
    mig1.unlink()
    with pytest.raises(ChecksumMismatch, match="missing on disk"):
        verify_schema_checksums(conn, directory=tmp_path)


def test_migrate_governed_preflight_blocks_pending_on_tamper(tmp_path: Path):
    mig1 = tmp_path / "0001_initial.sql"
    mig1.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8")
    conn = connect(":memory:")
    assert migrate_governed(conn, directory=tmp_path) == 1

    # Add pending migration 2, but tamper with migration 1
    (tmp_path / "0002_pending.sql").write_text(
        "CREATE TABLE beta (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8"
    )
    mig1.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY, tampered INT) STRICT;", encoding="utf-8")

    with pytest.raises(ChecksumMismatch, match="changed on disk after being applied"):
        migrate_governed(conn, directory=tmp_path)

    # Current version did not advance and beta was not created
    assert current_version(conn) == 1
    assert "beta" not in table_names(conn)


@pytest.mark.parametrize(
    "bad_name",
    [
        "invalid.sql",
        "01_name.sql",
        "0001-dash.sql",
        "0001_CamelCase.sql",
        "0001.sql",
    ],
)
def test_migration_filename_validation(tmp_path: Path, bad_name: str):
    (tmp_path / bad_name).write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    with pytest.raises(MigrationError, match="is not NNNN_name.sql"):
        discover_migrations(tmp_path)


def test_gapless_version_ordering_starting_at_zero(tmp_path: Path):
    (tmp_path / "0000_zero.sql").write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    with pytest.raises(MigrationError, match="gapless 1-based sequence"):
        discover_migrations(tmp_path)


def test_gapless_version_ordering_gap_rejected(tmp_path: Path):
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id INT);", encoding="utf-8")
    (tmp_path / "0003_third.sql").write_text("CREATE TABLE c (id INT);", encoding="utf-8")
    with pytest.raises(MigrationError, match="gapless 1-based sequence"):
        discover_migrations(tmp_path)


def test_gapless_version_ordering_starting_at_two(tmp_path: Path):
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE b (id INT);", encoding="utf-8")
    with pytest.raises(MigrationError, match="gapless 1-based sequence"):
        discover_migrations(tmp_path)


def test_fk_enforcement_deferred_violation_rolls_back(tmp_path: Path):
    mig_dir = tmp_path / "schema"
    mig_dir.mkdir()
    (mig_dir / "0001_initial.sql").write_text(
        "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT;\n"
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id)) STRICT;\n",
        encoding="utf-8",
    )
    (mig_dir / "0002_bad_fk.sql").write_text(
        "PRAGMA defer_foreign_keys = ON;\n"
        "INSERT INTO child (id, parent_id) VALUES (1, 999);\n",
        encoding="utf-8",
    )
    conn = connect(tmp_path / "test.db")

    with pytest.raises(MigrationError, match="foreign key check failed") as exc_info:
        migrate_governed(conn, directory=mig_dir)

    assert issubclass(exc_info.type, MigrationError)
    assert issubclass(ForeignKeyViolationError, MigrationError)
    assert isinstance(exc_info.value, ForeignKeyViolationError)
    assert current_version(conn) == 1
    assert "child" in table_names(conn)
    assert conn.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0


def test_fk_enforcement_immediate_violation_rolls_back(tmp_path: Path):
    mig_dir = tmp_path / "schema"
    mig_dir.mkdir()
    (mig_dir / "0001_initial.sql").write_text(
        "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT;\n"
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id)) STRICT;\n",
        encoding="utf-8",
    )
    (mig_dir / "0002_bad_fk.sql").write_text(
        "INSERT INTO child (id, parent_id) VALUES (1, 999);\n",
        encoding="utf-8",
    )
    conn = connect(tmp_path / "test_imm.db")

    with pytest.raises(MigrationError, match="foreign key check failed") as exc_info:
        migrate_governed(conn, directory=mig_dir)

    assert isinstance(exc_info.value, ForeignKeyViolationError)
    assert current_version(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0


def test_single_transaction_isolation_rollback_on_syntax_error(tmp_path: Path):
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
        migrate_governed(conn, directory=tmp_path)

    assert current_version(conn) == 1
    assert "alpha" in table_names(conn)
    assert "beta" not in table_names(conn)


def test_migrate_governed_idempotent_reapply():
    conn = connect(":memory:")
    v1 = migrate_governed(conn)
    rows1 = applied_migrations(conn)
    v2 = migrate_governed(conn)
    rows2 = applied_migrations(conn)
    assert v1 == v2
    assert rows1 == rows2
