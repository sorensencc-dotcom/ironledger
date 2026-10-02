"""Connection policy.

SQLite ships with ``PRAGMA foreign_keys`` OFF. Every connection IronLedger hands
out must have it ON, or the no-cascade evidence-retention guarantees in the
schema are silently unenforced. This module refuses to return a connection where
the pragma did not take.

The aggressive rejection test suite (float rejection, duplicate identity,
timestamp shape, identity-version immutability) lands in Phase 1 task 3. Task 2
only needs a connection that actually enforces foreign keys so migration and
structural tests are meaningful.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_JOURNAL_MODES = {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY"}

__all__ = ["ForeignKeysNotEnforced", "connect"]


class ForeignKeysNotEnforced(RuntimeError):
    """A connection could not be placed in foreign-key-enforcing mode."""


def _journal_mode() -> str:
    raw = os.environ.get("IRONLEDGER_JOURNAL_MODE", "WAL").strip().upper()
    return raw if raw in _JOURNAL_MODES else "WAL"


def connect(database: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys enforced.

    Journal mode defaults to WAL. Set ``IRONLEDGER_JOURNAL_MODE=DELETE`` when the
    database file lives on a Docker Desktop bind mount: WAL locking there has
    corrupted this database twice.

    ``database`` may be a filesystem path or ``":memory:"``. Raises
    :class:`ForeignKeysNotEnforced` if ``PRAGMA foreign_keys`` does not report
    ``1`` after being set.
    """
    try:
        conn = sqlite3.connect(str(database), check_same_thread=False)
    except TypeError:
        conn = sqlite3.connect(str(database))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        (fk_state,) = conn.execute("PRAGMA foreign_keys").fetchone()
        if fk_state != 1:
            raise ForeignKeysNotEnforced(
                f"PRAGMA foreign_keys reported {fk_state!r} after being set to ON"
            )
        # WAL is unavailable for pure in-memory databases. On a Docker Desktop
        # bind mount it also reports success and then corrupts pages, so the
        # container sets IRONLEDGER_JOURNAL_MODE=DELETE.
        if str(database) != ":memory:":
            try:
                conn.execute(f"PRAGMA journal_mode = {_journal_mode()}")
            except sqlite3.OperationalError:
                pass
        conn.execute("PRAGMA busy_timeout = 5000")
    except Exception:
        conn.close()
        raise
    return conn
