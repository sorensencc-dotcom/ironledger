"""Hardened forward-only migration runner with pre-flight checksums and foreign-key checks.

Guarantees:
- Migrations apply in ascending numeric order (0001_*.sql before 0002_*.sql).
- Gapless 1-based sequence starting at 1.
- Pre-flight SHA-256 schema verification ensures no previously applied migration
  has been altered or removed on disk before pending migrations run.
- Single-transaction isolation per migration using BEGIN IMMEDIATE.
- Mandatory PRAGMA foreign_keys = ON and PRAGMA foreign_key_check validation:
  any foreign-key violation rolls back the migration and raises ForeignKeyViolationError
  (subclass of MigrationError), preventing schema version advancement.
- Re-running migrations is idempotent once recorded.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "MigrationError",
    "ChecksumMismatch",
    "ForeignKeyViolationError",
    "Migration",
    "discover_migrations",
    "applied_migrations",
    "current_version",
    "verify_schema_checksums",
    "migrate_governed",
    "migrate",
]

_FILENAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql\Z")

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version        INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    checksum       TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
) STRICT;
"""


class MigrationError(RuntimeError):
    """A migration set is malformed, out of order, or violated constraints."""


class ChecksumMismatch(MigrationError):
    """A recorded migration's file text changed or is missing after it was applied."""


class ForeignKeyViolationError(MigrationError):
    """A migration violated foreign key constraints or failed PRAGMA foreign_key_check."""


class Migration(NamedTuple):
    version: int
    name: str
    sql: str
    checksum: str


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover_migrations(directory: str | Path | None = None) -> list[Migration]:
    """Return the ordered migration set.

    With no argument, read the packaged ``ironledger.db.schema`` directory.
    A path argument reads ``*.sql`` from that directory instead.
    """
    entries: list[tuple[int, str, str]] = []
    if directory is None:
        for entry in resources.files("ironledger.db.schema").iterdir():
            if entry.name.endswith(".sql"):
                match = _FILENAME.match(entry.name)
                if not match:
                    raise MigrationError(f"migration filename {entry.name!r} is not NNNN_name.sql")
                entries.append(
                    (int(match["version"]), match["name"], entry.read_text(encoding="utf-8"))
                )
    else:
        for path in sorted(Path(directory).glob("*.sql")):
            match = _FILENAME.match(path.name)
            if not match:
                raise MigrationError(f"migration filename {path.name!r} is not NNNN_name.sql")
            entries.append((int(match["version"]), match["name"], path.read_text(encoding="utf-8")))

    entries.sort(key=lambda row: row[0])
    migrations = [
        Migration(version=v, name=n, sql=s, checksum=_checksum(s)) for v, n, s in entries
    ]
    for index, migration in enumerate(migrations, start=1):
        if migration.version != index:
            raise MigrationError(
                f"migration versions must be a gapless 1-based sequence; "
                f"expected {index}, found {migration.version} ({migration.name})"
            )
    return migrations


def _ensure_bootstrap(conn: sqlite3.Connection) -> None:
    conn.executescript(_BOOTSTRAP)
    conn.commit()


def applied_migrations(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """Return ``(version, name, checksum)`` for each applied migration, in order."""
    _ensure_bootstrap(conn)
    return list(
        conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        )
    )


def current_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none."""
    _ensure_bootstrap(conn)
    (value,) = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(value)


def verify_schema_checksums(
    conn: sqlite3.Connection, directory: str | Path | None = None
) -> bool:
    """Validate that previously recorded migrations in schema_migrations have not been altered on disk.

    Returns True if all applied migrations match disk checksums.
    Raises :class:`ChecksumMismatch` if any recorded migration's checksum differs on disk
    or if an applied migration is missing on disk.
    """
    applied = applied_migrations(conn)
    if not applied:
        return True

    discovered = {m.version: m for m in discover_migrations(directory)}

    for version, name, recorded_checksum in applied:
        disk_migration = discovered.get(version)
        if disk_migration is None:
            raise ChecksumMismatch(
                f"migration {version:04d}_{name} was previously applied but is missing on disk"
            )
        if disk_migration.checksum != recorded_checksum:
            raise ChecksumMismatch(
                f"migration {version:04d}_{name} changed on disk after being applied"
            )

    return True


def migrate_governed(
    conn: sqlite3.Connection, directory: str | Path | None = None
) -> int:
    """Apply pending migrations with pre-flight checksum verification and foreign-key validation.

    Guarantees:
    - Pre-flight SHA-256 validation of all already-applied migrations.
    - Each pending migration executes in an isolated transaction using BEGIN IMMEDIATE.
    - PRAGMA foreign_keys = ON is enforced.
    - PRAGMA foreign_key_check is verified before COMMIT. If violations are detected,
      the transaction is rolled back, raising ForeignKeyViolationError with violation details.
    - Bookkeeping row is committed atomically with migration statements.
    - Returns the resulting schema version.
    """
    migrations = discover_migrations(directory)
    _ensure_bootstrap(conn)

    # 1. Pre-flight schema checksum verification
    verify_schema_checksums(conn, directory)

    # 2. Identify applied versions
    applied = {version for version, _name, _checksum in applied_migrations(conn)}

    # 3. Apply pending migrations
    for migration in migrations:
        if migration.version in applied:
            continue

        applied_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bookkeeping = (
            "INSERT INTO schema_migrations (version, name, checksum, applied_at_utc) VALUES "
            f"({migration.version}, '{migration.name}', '{migration.checksum}', '{applied_at}');"
        )

        conn.execute("PRAGMA foreign_keys = ON;")
        script = f"BEGIN IMMEDIATE;\n{migration.sql}\n{bookkeeping}\n"

        try:
            conn.executescript(script)
            violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
            if violations:
                conn.rollback()
                raise ForeignKeyViolationError(
                    f"foreign key check failed in migration {migration.version:04d}_{migration.name}: {violations}"
                )
            conn.commit()
        except ForeignKeyViolationError:
            raise
        except sqlite3.IntegrityError as exc:
            if conn.in_transaction:
                conn.rollback()
            if "foreign key" in str(exc).lower():
                raise ForeignKeyViolationError(
                    f"foreign key check failed in migration {migration.version:04d}_{migration.name}: {exc}"
                ) from exc
            raise
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    return current_version(conn)


migrate = migrate_governed
