"""Multi-tenant ledger registry, topology management, and compile locks."""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from ironledger.ledger.models import (
    CURRENCY_PATTERN,
    LEDGER_ID_PATTERN,
    LedgerTopology,
)


def validate_and_resolve_ledger_root(base_path: Path | str, storage_root: Path | str) -> Path:
    """Resolve and validate that storage_root is safely contained within base_path.

    Rejects directory traversal attempts and any symlinks in the path hierarchy.
    """
    base = Path(base_path).resolve()
    storage_path = Path(storage_root)

    # 1. Reject any symlinks in the path hierarchy
    raw_target = storage_path if storage_path.is_absolute() else (base / storage_path)
    
    curr = raw_target
    while True:
        if curr.is_symlink() or os.path.islink(curr):
            raise ValueError(f"Symlinks are strictly prohibited in ledger paths: {curr}")
        if curr == base or curr.parent == curr:
            break
        curr = curr.parent

    # 2. Confinement check
    resolved = raw_target.resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError(f"Storage root '{storage_root}' resolves outside base directory '{base}'")

    # Double check resolved path does not contain symlinks
    curr = resolved
    while True:
        if curr.is_symlink() or os.path.islink(curr):
            raise ValueError(f"Symlinks are strictly prohibited in ledger paths: {curr}")
        if curr == base or curr.parent == curr:
            break
        curr = curr.parent

    return resolved


class LedgerRegistry:
    """Registry for managing multi-tenant ledgers, paths, and compile lockfiles."""

    def __init__(self, conn: sqlite3.Connection, base_path: Path | str) -> None:
        self.conn = conn
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _check_storage_root_unique(self, ledger_id: str, resolved_path: Path) -> None:
        """Ensure no other ledger shares the same canonical storage path (case-insensitive on Windows)."""
        cur = self.conn.execute("SELECT ledger_id, storage_root FROM ledgers WHERE ledger_id != ?", (ledger_id,))
        for other_id, other_storage in cur.fetchall():
            if not other_storage:
                continue
            try:
                other_resolved = (self.base_path / other_storage).resolve()
                if os.name == "nt":
                    if str(other_resolved).lower() == str(resolved_path).lower():
                        raise ValueError(f"Storage root '{resolved_path}' is already in use by ledger '{other_id}'")
                else:
                    if other_resolved == resolved_path:
                        raise ValueError(f"Storage root '{resolved_path}' is already in use by ledger '{other_id}'")
            except Exception as e:
                if isinstance(e, ValueError) and "already in use" in str(e):
                    raise
                continue

    def create_ledger(
        self,
        name: str,
        root_account: str = "Assets",
        base_currency: str = "USD",
        storage_root: str = "",
        ledger_id: str | None = None,
    ) -> LedgerTopology:
        """Register a new tenant ledger in the catalog and ensure its directory exists."""
        if not isinstance(name, str) or not (1 <= len(name) <= 128):
            raise ValueError("Invalid name length")
        if not isinstance(root_account, str) or not (1 <= len(root_account) <= 128):
            raise ValueError(f"Invalid root_account length: {len(root_account) if isinstance(root_account, str) else 'non-string'}")

        if ledger_id is None:
            slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower()
            if not slug or not LEDGER_ID_PATTERN.match(slug):
                slug = f"ledger_{abs(hash(name)) % 1000000}"
            ledger_id = slug

        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")
        if not isinstance(base_currency, str) or not CURRENCY_PATTERN.match(base_currency):
            raise ValueError(f"Invalid base_currency: {base_currency!r}")

        effective_storage = storage_root if storage_root else ledger_id
        resolved_path = validate_and_resolve_ledger_root(self.base_path, effective_storage)

        in_tx = self.conn.in_transaction
        if not in_tx:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            # Reject ID collisions within transaction
            if self.get_ledger(ledger_id) is not None:
                raise ValueError(f"Ledger with ID '{ledger_id}' already exists")

            # Check unique storage root within transaction
            self._check_storage_root_unique(ledger_id, resolved_path)
            resolved_path.mkdir(parents=True, exist_ok=True)

            self.conn.execute(
                """
                INSERT INTO ledgers (ledger_id, name, root_account, base_currency, storage_root, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (ledger_id, name, root_account, base_currency, effective_storage),
            )
            if not in_tx:
                self.conn.execute("COMMIT")
        except Exception:
            if not in_tx and self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

        res = self.get_ledger(ledger_id)
        if res is None:
            raise RuntimeError(f"Failed to retrieve created ledger {ledger_id}")
        return res

    def get_ledger(self, ledger_id: str) -> LedgerTopology | None:
        """Retrieve a ledger topology by ID."""
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")

        cur = self.conn.execute(
            """
            SELECT ledger_id, name, root_account, base_currency, storage_root, is_active, created_at
            FROM ledgers
            WHERE ledger_id = ?
            """,
            (ledger_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        return LedgerTopology(
            ledger_id=row[0],
            name=row[1],
            root_account=row[2],
            base_currency=row[3],
            storage_root=row[4],
            is_active=bool(row[5]),
            created_at_utc=row[6],
        )

    def list_ledgers(self, include_inactive: bool = False) -> list[LedgerTopology]:
        """List all registered ledgers."""
        query = """
            SELECT ledger_id, name, root_account, base_currency, storage_root, is_active, created_at
            FROM ledgers
        """
        params: tuple = ()
        if not include_inactive:
            query += " WHERE is_active = 1"
        query += " ORDER BY ledger_id ASC"

        cur = self.conn.execute(query, params)
        rows = cur.fetchall()
        return [
            LedgerTopology(
                ledger_id=r[0],
                name=r[1],
                root_account=r[2],
                base_currency=r[3],
                storage_root=r[4],
                is_active=bool(r[5]),
                created_at_utc=r[6],
            )
            for r in rows
        ]

    def register_storage_root(self, ledger_id: str, storage_root: Path | str) -> Path:
        """Validate, register, and update the storage root for a ledger."""
        resolved = validate_and_resolve_ledger_root(self.base_path, storage_root)

        in_tx = self.conn.in_transaction
        if not in_tx:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._check_storage_root_unique(ledger_id, resolved)
            resolved.mkdir(parents=True, exist_ok=True)

            self.conn.execute(
                "UPDATE ledgers SET storage_root = ? WHERE ledger_id = ?",
                (str(storage_root), ledger_id),
            )
            if not in_tx:
                self.conn.execute("COMMIT")
        except Exception:
            if not in_tx and self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

        return resolved

    def get_lock_path(self, ledger_id: str) -> Path:
        """Get the filesystem lockfile path for a ledger."""
        if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
            raise ValueError(f"Invalid ledger_id: {ledger_id!r}")
        return self.base_path / f".compile.{ledger_id}.lock"

    @contextmanager
    def acquire_compile_lock(self, ledger_id: str) -> Generator[Path, None, None]:
        """Acquire an exclusive cross-process lock for compiling a specific tenant ledger."""
        lock_path = self.get_lock_path(ledger_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        f = open(lock_path, "a+b")
        try:
            f.write(b" ")
            f.flush()
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield lock_path
        finally:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            f.close()
