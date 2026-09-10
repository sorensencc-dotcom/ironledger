"""Lockfile acquisition, stale lock inspection, and sync utilities for Phase 7."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys

__all__ = [
    "SyncLockActiveError",
    "SyncLockPermissionError",
    "acquire_lock",
    "release_lock",
    "inspect_and_reclaim_if_stale",
]


class SyncLockActiveError(Exception):
    """A live sync lock is held; current invocation halts fail-closed."""


class SyncLockPermissionError(Exception):
    """Could not read or delete the lock file due to OS permission error."""


def _get_hostname() -> str:
    return socket.gethostname()


def _pid_exists(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        if sys.platform == "win32":
            return False  # conservative fallback
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, not ours


def _pid_is_ironledger(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        import psutil
        p = psutil.Process(pid)
        cmd = " ".join(p.cmdline()).lower()
        return "ironledger" in p.name().lower() or "ironledger" in cmd
    except Exception:
        return False


def _write_lock(lock_path: Path) -> None:
    data = json.dumps({
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hostname": _get_hostname(),
    })
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)


def acquire_lock(lock_path: Path) -> None:
    """Atomically create lock. Raises SyncLockActiveError if already held."""
    if lock_path.exists():
        inspect_and_reclaim_if_stale(lock_path)
    try:
        _write_lock(lock_path)
    except FileExistsError as exc:
        raise SyncLockActiveError(f"Lock already held at {lock_path}") from exc


def release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except PermissionError as exc:
        raise SyncLockPermissionError(f"Cannot release lock at {lock_path}: {exc}") from exc


def inspect_and_reclaim_if_stale(lock_path: Path) -> bool:
    """Inspect existing lock; reclaim if stale. Returns True if reclaimed.

    Outcome table (evaluated in order):
    1. JSON malformed/unreadable -> log LOCK_PARSE_ERROR + reclaim.
    2. hostname != current host -> SyncLockActiveError (foreign lock never reclaimed).
    3. PID exists + ironledger process -> SyncLockActiveError.
    4. PID exists, unrelated (PID reuse) -> reclaim.
    5. PID dead -> reclaim.
    6. Permission error reading/deleting -> SyncLockPermissionError + fail closed.
    """
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise SyncLockPermissionError(f"Cannot read lock: {exc}") from exc

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Lock data must be a JSON object")
        pid = int(data["pid"])
        hostname = str(data.get("hostname", ""))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        # Outcome 1: malformed JSON -> reclaim
        try:
            lock_path.unlink(missing_ok=True)
        except PermissionError as exc:
            raise SyncLockPermissionError(f"Cannot delete malformed lock: {exc}") from exc
        return True

    # Outcome 2: foreign hostname -> fail closed
    curr_host = _get_hostname()
    if hostname and hostname != curr_host and hostname not in ("localhost", "127.0.0.1"):
        raise SyncLockActiveError(
            f"Lock held by foreign host {hostname!r}; remove manually."
        )

    # Outcomes 3 + 4
    if _pid_exists(pid) and _pid_is_ironledger(pid):
        raise SyncLockActiveError(f"Active IronLedger sync (PID {pid}) is running.")

    # Outcome 5: dead PID (or PID reuse with unrelated process) -> reclaim
    try:
        lock_path.unlink(missing_ok=True)
    except PermissionError as exc:
        raise SyncLockPermissionError(f"Cannot delete stale lock: {exc}") from exc
    return True
