"""Compile lock manager and full staging-to-live compile pipeline.

On bean-check failure, staging is quarantined into ``failed-<run_id>``, a
``bean-check.txt`` transcript is written, the compile run is journalled as
failed, and an error audit event is emitted. On success, rendered files are
written to ``.staging/<run_id>/`` first, then copied into place with sibling
temp + ``os.replace`` (A4.1 copy semantics, so ``.staging`` stays byte-complete
until the explicit ``shutil.rmtree`` after the index update), the live output
hash is read back and verified, the compile run is finished, and the
``ledger_entries`` / ``ledger_postings`` index is repopulated.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from ironledger.audit import append_audit_event
from ironledger.compile.beancheck import run_bean_check
from ironledger.compile.errors import (
    BeanCheckFailedError,
    CompileError,
    CompileLockedError,
)
from ironledger.compile.hashing import (
    compute_actual_output_hash,
    compute_input_hash,
    compute_intended_output_hash,
)
from ironledger.compile.journal import (
    append_compile_journal,
    fail_compile_run,
    finish_compile_run,
    get_active_started_run,
    start_compile_run,
)
from ironledger.compile.model import load_approved_set, validate_approved_set
from ironledger.compile.render import render_ledger
from ironledger.conventions import validate_utc_timestamp
from dataclasses import dataclass


@dataclass(frozen=True)
class CompileSummary:
    compile_run_id: str
    entry_count: int
    year_files: tuple[str, ...]
    output_hash: str


def _fsync_dir(dir_path: Path) -> None:
    try:
        dfd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except (OSError, AttributeError):
        pass


def _atomic_write_file(dst: Path, data: bytes) -> None:
    """Write ``data`` to ``dst`` atomically via a sibling temp file + os.replace.

    Copy semantics: the source (``.staging/<run_id>/``) is untouched, so a crash
    between the temp write and the replace never destroys the staged copy.
    """
    tmp = dst.parent / (dst.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(dst))
    _fsync_dir(dst.parent)


def _replace_ledger_index(
    conn: sqlite3.Connection, compile_run_id: str, approved_set: Any, now_utc: str
) -> None:
    # Delete prior index rows (cascade deletes ledger_postings)
    conn.execute("DELETE FROM ledger_entries")

    for tx in approved_set.transactions:
        entry_id = f"le-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO ledger_entries (ledger_entry_id, staged_transaction_id, compile_run_id, "
            " entry_date, flag, payee, narration, created_at_utc) "
            "VALUES (?, ?, ?, ?, '*', ?, ?, ?)",
            (
                entry_id,
                tx.staged_transaction_id,
                compile_run_id,
                tx.proposed_date,
                tx.payee,
                tx.narration,
                now_utc,
            ),
        )
        for p in tx.postings:
            p_id = f"lp-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO ledger_postings (ledger_posting_id, ledger_entry_id, source_record_id, "
                " account, minor_units, currency, minor_unit_scale, identity_algo_version, "
                " identity_method, identity_fingerprint, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    p_id,
                    entry_id,
                    p.source_record_id,
                    p.account,
                    p.minor_units,
                    p.currency,
                    p.minor_unit_scale,
                    p.identity_algo_version,
                    p.identity_method,
                    p.identity_fingerprint,
                    now_utc,
                ),
            )
    conn.commit()


@contextmanager
def acquire_compile_lock(ledger_dir: Path) -> Generator[Path, None, None]:
    lock_file = ledger_dir / ".compile.lock"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    # Atomic create-or-fail: O_CREAT | O_EXCL is a single syscall on POSIX and
    # Windows, so there is no check-then-write race. A hard crash (SIGKILL /
    # power-loss) that skips the `finally` below strands the file; the next
    # caller then hits FileExistsError here and gets an actionable refusal
    # instead of a silent check-then-write that could double-run a compile.
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise CompileLockedError(
            f"Compile lock is currently held at {lock_file}. "
            f"If no compile is running, remove that file and retry."
        )
    try:
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        os.write(fd, f"pid={os.getpid()}\nsince={since}\n".encode("utf-8"))
    finally:
        os.close(fd)
    try:
        yield lock_file
    finally:
        if lock_file.exists():
            lock_file.unlink()


def compile_approved(
    conn: sqlite3.Connection,
    ledger_dir: Path,
    *,
    now_utc: str | None = None,
    bean_check_bin: str | None = None,
) -> CompileSummary:
    ledger_dir = Path(ledger_dir)
    now = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(now)

    with acquire_compile_lock(ledger_dir):
        dangling = get_active_started_run(conn)
        if dangling is not None:
            raise CompileError(
                f"A previous compile run {dangling['compile_run_id']} is still 'started'; "
                "recovery is required before a new compile."
            )

        approved_set = load_approved_set(conn)
        validate_approved_set(approved_set)

        rendered = render_ledger(approved_set)
        in_hash = compute_input_hash(approved_set)
        intended_hash = compute_intended_output_hash(rendered)

        run_id = f"crun-{uuid.uuid4().hex[:12]}"
        staging_dir = ledger_dir / ".staging" / run_id
        for rel_path, data in rendered.items():
            dest = staging_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        check_res = run_bean_check(staging_dir / "main.beancount", bean_check_bin=bean_check_bin)

        start_compile_run(
            conn,
            compile_run_id=run_id,
            beancount_version=check_res.beancount_version,
            compiler_version=check_res.compiler_version,
            input_hash=in_hash,
            intended_output_hash=intended_hash,
            now_utc=now,
        )

        if not check_res.ok:
            failed_dir = ledger_dir / ".staging" / f"failed-{run_id}"
            shutil.move(str(staging_dir), str(failed_dir))
            (failed_dir / "bean-check.txt").write_text(
                check_res.stderr or check_res.stdout, encoding="utf-8"
            )
            fail_compile_run(
                conn, run_id, detail=f"bean-check exit code {check_res.exit_code}", now_utc=now
            )
            append_audit_event(
                conn,
                actor="operator",
                action="compile",
                target=run_id,
                result="error",
                compile_run_id=run_id,
                ts_utc=now,
            )
            raise BeanCheckFailedError(
                f"bean-check validation failed:\n{check_res.stderr}"
            )

        append_compile_journal(conn, run_id, "bean_checked", now_utc=now)

        # Atomic replacement in fixed order: accounts.beancount, main.beancount,
        # then sorted txns/YYYY.beancount. A4.1: copy semantics (sibling temp +
        # os.replace) keep .staging byte-complete so a crash mid-replace is
        # recoverable from staging as well as from a re-render.
        (ledger_dir / "txns").mkdir(parents=True, exist_ok=True)
        year_files = sorted(p for p in rendered if p.startswith("txns/"))
        order = ["accounts.beancount", "main.beancount"] + year_files
        for rel in order:
            dst = ledger_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_file(dst, rendered[rel])

        # Drop any live txns/*.beancount not in the intended set (a year the
        # approved set stopped covering). recover.py:178-185 does this; without
        # the same prune here an orphan year file survives and `compile status`
        # (globs the whole tree) reports a false "Hash Matches: NO" on a tree
        # that is exactly as compiled.
        intended_txns = {p for p in rendered if p.startswith("txns/")}
        for stale in sorted((ledger_dir / "txns").glob("*.beancount")):
            if f"txns/{stale.name}" not in intended_txns:
                stale.unlink()

        _fsync_dir(ledger_dir)
        append_compile_journal(conn, run_id, "replaced", now_utc=now)

        # Read back live files and verify the on-disk hash matches intent.
        actual_hash = compute_actual_output_hash(ledger_dir, year_files)
        if actual_hash != intended_hash:
            raise CompileError(
                f"Live ledger output hash mismatch: actual={actual_hash} != intended={intended_hash}"
            )

        # Index BEFORE finish: a crash between these two must leave the run
        # `started` (recover.py Row 2 re-runs and re-replaces idempotently), not
        # `succeeded` over the previous run's index rows with no path back
        # (get_active_started_run would return None and `compile recover` would
        # report nothing to recover).
        _replace_ledger_index(conn, run_id, approved_set, now)
        finish_compile_run(conn, run_id, actual_output_hash=actual_hash, now_utc=now)

        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        append_audit_event(
            conn,
            actor="operator",
            action="compile",
            target=run_id,
            result="ok",
            compile_run_id=run_id,
            input_hash=in_hash,
            output_hash=actual_hash,
            ts_utc=now,
        )

        return CompileSummary(
            compile_run_id=run_id,
            entry_count=len(approved_set.transactions),
            year_files=tuple(year_files),
            output_hash=actual_hash,
        )
