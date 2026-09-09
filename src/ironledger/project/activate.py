"""Lock, hash-check, parse, and atomically activate a projection rebuild."""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ironledger.audit import append_audit_event
from ironledger.compile.errors import CompileLockedError
from ironledger.compile.hashing import compute_actual_output_hash
from ironledger.compile.journal import get_latest_successful_run
from ironledger.compile.writer import acquire_lock
from ironledger.project.builder import write_staging_projection
from ironledger.project.errors import (
    ProjectError,
    ProjectHashMismatchError,
    ProjectInputError,
    ProjectLockedError,
    format_hash_mismatch,
)
from ironledger.project.migrate import PROJECT_SCHEMA_VERSION
from ironledger.project.parse import discover_year_files, parse_ledger


@dataclass(frozen=True)
class ProjectSummary:
    compile_run_id: str
    schema_version: int
    entry_count: int
    posting_count: int
    account_count: int
    ledger_output_hash: str
    projection_path: Path


def default_projection_dir(ledger_dir: Path) -> Path:
    return Path(ledger_dir).parent / "projection"


def rebuild_projection(
    conn: sqlite3.Connection,
    ledger_dir: Path,
    projection_dir: Path | None = None,
    *,
    now_utc: str | None = None,
) -> ProjectSummary:
    ledger_dir = Path(ledger_dir)
    now = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    projection_dir = Path(projection_dir or default_projection_dir(ledger_dir))
    projection_dir.mkdir(parents=True, exist_ok=True)

    compile_run_id: str | None = None
    try:
        # Compile lock first, then project lock; nested `with` releases in reverse.
        with acquire_lock(ledger_dir, name=".compile.lock"):
            with acquire_lock(
                projection_dir, name=".project.lock", error_cls=ProjectLockedError
            ):
                run = get_latest_successful_run(conn)
                if run is None:
                    raise ProjectInputError("no successful compile run")
                compile_run_id = run["compile_run_id"]

                year_files = discover_year_files(ledger_dir)
                on_disk = compute_actual_output_hash(ledger_dir, year_files)
                if on_disk != run["actual_output_hash"]:
                    raise ProjectHashMismatchError(
                        format_hash_mismatch(
                            on_disk=on_disk,
                            expected=run["actual_output_hash"],
                            ledger_dir=ledger_dir,
                        )
                    )

                parsed = parse_ledger(ledger_dir)
                build_id = uuid.uuid4().hex
                staging = projection_dir / ".staging" / build_id
                write_staging_projection(
                    parsed,
                    staging,
                    compile_run_id=run["compile_run_id"],
                    ledger_input_hash=run["input_hash"],
                    ledger_output_hash=on_disk,
                    beancount_version=run["beancount_version"],
                    compiler_version=run["compiler_version"],
                    built_at_utc=now,
                )
                live_sqlite = projection_dir / "projection.sqlite"
                live_manifest = projection_dir / "projection.manifest.json"
                # Sqlite then manifest so a crash between them cannot swap only the manifest.
                os.replace(staging / "projection.sqlite", live_sqlite)
                os.replace(staging / "projection.manifest.json", live_manifest)
                shutil.rmtree(staging, ignore_errors=True)

                append_audit_event(
                    conn,
                    actor="operator",
                    action="project",
                    target=str(projection_dir),
                    result="ok",
                    ts_utc=now,
                    compile_run_id=run["compile_run_id"],
                )
                conn.commit()
                return ProjectSummary(
                    compile_run_id=run["compile_run_id"],
                    schema_version=PROJECT_SCHEMA_VERSION,
                    entry_count=len(parsed.entries),
                    posting_count=sum(len(entry.postings) for entry in parsed.entries),
                    account_count=len({acct.account for acct in parsed.accounts}),
                    ledger_output_hash=on_disk,
                    projection_path=live_sqlite,
                )
    except (ProjectError, CompileLockedError):
        append_audit_event(
            conn,
            actor="operator",
            action="project",
            target=str(projection_dir),
            result="error",
            ts_utc=now,
            compile_run_id=compile_run_id,
        )
        conn.commit()
        raise
