"""Lockfile acquisition, stale lock inspection, and sync utilities for Phase 7."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import socket
import sys

logger = logging.getLogger("ironledger.pipeline.sync_daemon")

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
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                SYNCHRONIZE = 0x00100000
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
                )
                if not handle:
                    err = ctypes.GetLastError()
                    # Error 5 is ERROR_ACCESS_DENIED -> process exists but cannot open
                    if err == 5:
                        return True
                    return False
                try:
                    STILL_ACTIVE = 259
                    exit_code = ctypes.c_ulong()
                    if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return exit_code.value == STILL_ACTIVE
                    return True  # Fail closed: assume active
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                # Fail closed: on any query failure on Windows, assume process is active
                return True
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
    except ImportError:
        # Fail closed: without psutil, assume alive PID could be IronLedger
        return True
    except Exception:
        return True


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
    except FileNotFoundError:
        pass
    except PermissionError as exc:
        logger.error("LOCK_PERMISSION_ERROR: permission error on %s: %s", lock_path, exc)
        raise SyncLockPermissionError(f"Cannot release lock at {lock_path}: {exc}") from exc


def inspect_and_reclaim_if_stale(lock_path: Path) -> bool:
    """Inspect existing lock; reclaim if stale. Returns True if reclaimed.

    Outcome table (evaluated in order):
    1. Permission error reading -> SyncLockPermissionError + fail closed.
    2. JSON malformed/unreadable -> log LOCK_PARSE_ERROR + SyncLockActiveError (fail closed).
    3. hostname != current host -> SyncLockActiveError (foreign lock never reclaimed).
    4. PID exists + ironledger process -> SyncLockActiveError.
    5. PID exists, unrelated (PID reuse) -> reclaim.
    6. PID dead -> reclaim.
    7. Permission error deleting -> SyncLockPermissionError + fail closed.
    """
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except PermissionError as exc:
        logger.error("LOCK_PERMISSION_ERROR: permission error on %s: %s", lock_path, exc)
        raise SyncLockPermissionError(f"Cannot read lock: {exc}") from exc

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Lock data must be a JSON object")
        pid = int(data["pid"])
        hostname = str(data.get("hostname", ""))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.error(
            "LOCK_PARSE_ERROR: malformed lock file at %s (%s) - failing closed",
            lock_path,
            exc,
        )
        raise SyncLockActiveError(
            f"Lock file at {lock_path} is malformed or unreadable; manual operator recovery required"
        ) from exc

    # Outcome 3: foreign hostname -> fail closed
    curr_host = _get_hostname()
    if hostname and hostname != curr_host:
        raise SyncLockActiveError(
            f"Lock held by foreign host {hostname!r}; remove manually."
        )

    # Outcome 4: PID exists (live process) -> fail closed
    if _pid_exists(pid):
        raise SyncLockActiveError(f"Active process (PID {pid}) holds lock at {lock_path}.")

    # Outcome 5: dead PID -> reclaim
    try:
        lock_path.unlink(missing_ok=True)
    except FileNotFoundError:
        return True
    except PermissionError as exc:
        logger.error("LOCK_PERMISSION_ERROR: permission error on %s: %s", lock_path, exc)
        raise SyncLockPermissionError(f"Cannot delete stale lock: {exc}") from exc
    logger.info("STALE_LOCK_RECLAIMED: lock at %s reclaimed (pid=%s)", lock_path, pid)
    return True
