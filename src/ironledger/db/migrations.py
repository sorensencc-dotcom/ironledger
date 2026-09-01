"""Forward-only migration runner.

D-1b decision (recommended option, recorded here and in the Phase 1 plan):
numbered ``.sql`` files in ``ironledger/db/schema/`` applied by this minimal
runner. No ORM, no third-party migration framework, so every STRICT table and
foreign-key clause stays visible in plain SQL and reviewable in a diff.

Guarantees:

- Migrations apply in ascending numeric order (``0001_*.sql`` before ``0002_*.sql``).
- Each migration's statements and its ``schema_migrations`` bookkeeping row commit
  in a single transaction. An interruption or an error inside a migration rolls
  the whole file back; ``current_version`` never advances past a partially
  applied file.
- Re-running is a no-op once every file is recorded.
- Every recorded migration stores a SHA-256 checksum of the file text. If a
  file on disk changes after being applied, :func:`migrate` raises rather than
  silently diverging.
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
    "Migration",
    "discover_migrations",
    "current_version",
    "applied_migrations",
    "migrate",
]

_FILENAME = re.compile(r"(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql\Z")

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version       INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    checksum      TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
) STRICT;
"""


class MigrationError(RuntimeError):
    """A migration set is malformed or was applied out of order."""


class ChecksumMismatch(MigrationError):
    """A recorded migration's file text changed after it was applied."""


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
    A path argument (used by tests) reads ``*.sql`` from that directory instead.
    """
    entries: list[tuple[int, str, str]] = []
    if directory is None:
        for entry in resources.files("ironledger.db.schema").iterdir():
            match = _FILENAME.match(entry.name)
            if match:
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


def migrate(conn: sqlite3.Connection, directory: str | Path | None = None) -> int:
    """Apply every pending migration. Return the resulting schema version.

    Raises :class:`ChecksumMismatch` if an already-applied migration's file text
    has changed.
    """
    migrations = discover_migrations(directory)
    _ensure_bootstrap(conn)
    recorded = {version: checksum for version, _name, checksum in applied_migrations(conn)}

    for migration in migrations:
        if migration.version in recorded:
            if recorded[migration.version] != migration.checksum:
                raise ChecksumMismatch(
                    f"migration {migration.version:04d}_{migration.name} changed on disk "
                    f"after being applied"
                )
            continue

        # One transaction: the migration body plus its bookkeeping row. The
        # BEGIN/COMMIT live inside the script text because sqlite3.executescript
        # issues an implicit COMMIT of pending work before it runs, which would
        # otherwise close a transaction opened with a separate execute("BEGIN").
        # An error anywhere in the body raises before COMMIT is reached;
        # conn.rollback() then discards the partial file and current_version
        # does not advance.
        applied_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bookkeeping = (
            "INSERT INTO schema_migrations (version, name, checksum, applied_at_utc) VALUES "
            f"({migration.version}, '{migration.name}', '{migration.checksum}', '{applied_at}');"
        )
        script = f"BEGIN;\n{migration.sql}\n{bookkeeping}\nCOMMIT;"
        try:
            conn.executescript(script)
        except Exception:
            conn.rollback()
            raise

    return current_version(conn)
