"""Compile lock manager and staging pipeline up to bean-check validation.

On bean-check failure, staging is quarantined into ``failed-<run_id>``, a
``bean-check.txt`` transcript is written, the compile run is journalled as
failed, and an error audit event is emitted. The success path (atomic replace,
hash verification, ledger index) is implemented in Task 9.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from ironledger.audit import append_audit_event
from ironledger.compile.beancheck import run_bean_check
from ironledger.compile.errors import (
    BeanCheckFailedError,
    CompileError,
    CompileLockedError,
)
from ironledger.compile.hashing import (
    compute_input_hash,
    compute_intended_output_hash,
)
from ironledger.compile.journal import (
    fail_compile_run,
    get_active_started_run,
    start_compile_run,
)
from ironledger.compile.model import load_approved_set, validate_approved_set
from ironledger.compile.render import render_ledger
from ironledger.conventions import validate_utc_timestamp


@contextmanager
def acquire_compile_lock(ledger_dir: Path) -> Generator[Path, None, None]:
    lock_file = ledger_dir / ".compile.lock"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    if lock_file.exists():
        raise CompileLockedError(f"Compile lock is currently held at {lock_file}")
    try:
        lock_file.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
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
) -> None:
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

        raise CompileError("compile_approved success path is implemented in Task 9")
