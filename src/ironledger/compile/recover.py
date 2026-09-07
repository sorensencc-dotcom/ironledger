"""Recovery decision table for a compile run left in ``status = 'started'``.

``recover_dangling_compile`` implements section 11 of the Phase 3 compiler
design plus eng-review fold A4.1 (re-entrant recovery). It never consumes
``.staging`` incrementally: it re-derives the intended output from the current
approved set (spec decision 2 — output is a pure function of the approved set),
proves that derivation still matches the crashed run's frozen
``input_hash`` / ``intended_output_hash``, then writes only the live files that
do not already hold the intended bytes. A crash anywhere in that block leaves
the run re-eligible for exactly this path on the next ``compile recover``.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ironledger.audit import append_audit_event
from ironledger.compile.errors import AmbiguousRecoveryError, CompileError
from ironledger.compile.hashing import compute_input_hash, compute_intended_output_hash
from ironledger.compile.journal import (
    append_compile_journal,
    fail_compile_run,
    get_active_started_run,
    get_latest_successful_run,
)
from ironledger.compile.model import load_approved_set, validate_approved_set
from ironledger.compile.render import render_ledger
from ironledger.compile.writer import _atomic_write_file, _fsync_dir, _replace_ledger_index, acquire_compile_lock
from ironledger.conventions import validate_utc_timestamp


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    compile_run_id: str | None
    detail: str


def _live_tree_hash(ledger_dir: Path, rendered: dict[str, bytes]) -> str:
    """Hash the live ledger over exactly the intended relative-path set, missing files as b''."""
    live: dict[str, bytes] = {}
    for rel in rendered:
        fp = ledger_dir / rel
        live[rel] = fp.read_bytes() if fp.exists() else b""
    return compute_intended_output_hash(live)


def _live_tree_empty(ledger_dir: Path) -> bool:
    return not (ledger_dir / "main.beancount").exists() and not (ledger_dir / "accounts.beancount").exists()


def _staging_matches(staging_dir: Path, intended_hash: str) -> bool:
    if not staging_dir.exists():
        return False
    files: dict[str, bytes] = {}
    for root, _, names in os.walk(staging_dir):
        for n in names:
            fp = Path(root) / n
            files[fp.relative_to(staging_dir).as_posix()] = fp.read_bytes()
    return bool(files) and compute_intended_output_hash(files) == intended_hash


def _sweep_stale_temps(ledger_dir: Path) -> bool:
    """Unlink stale ``<name>.tmp-<hex>`` siblings left by a crash between
    ``_atomic_write_file``'s temp write and its ``os.replace``. Returns True if
    anything was removed."""
    removed = False
    for sweep_dir in (ledger_dir, ledger_dir / "txns"):
        if not sweep_dir.exists():
            continue
        for stale in sorted(sweep_dir.glob("*.tmp-*")):
            stale.unlink()
            removed = True
    return removed


def recover_dangling_compile(
    conn: sqlite3.Connection,
    ledger_dir: Path,
    *,
    now_utc: str | None = None,
) -> RecoveryDecision:
    ledger_dir = Path(ledger_dir)
    now = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(now)

    with acquire_compile_lock(ledger_dir):
        active = get_active_started_run(conn)
        if active is None:
            return RecoveryDecision(action="none", compile_run_id=None, detail="No active started compile run")

        run_id = active["compile_run_id"]
        intended_hash = active["intended_output_hash"]
        staging_dir = ledger_dir / ".staging" / run_id

        prev = get_latest_successful_run(conn)
        prev_hash = prev["actual_output_hash"] if prev else None

        staging_present = staging_dir.exists()
        staging_ok = _staging_matches(staging_dir, intended_hash)

        # Row 3: staging directory present but its hash does not equal
        # `intended_output_hash`. Refuse; the run stays `started`.
        if staging_present and not staging_ok:
            append_compile_journal(conn, run_id, "refused", detail="staging hash mismatch", now_utc=now)
            append_audit_event(
                conn, actor="operator", action="compile recover", target=run_id,
                result="error", compile_run_id=run_id, ts_utc=now,
            )
            raise AmbiguousRecoveryError(
                "staging hash mismatch: the staging directory is present but its hash does not "
                "equal intended_output_hash; re-run `ironledger compile` from a clean state."
            )

        # Re-derive the intended output from the current approved set (A4.1 basis).
        approved_set = load_approved_set(conn)
        try:
            validate_approved_set(approved_set)
            approved_valid = True
        except CompileError:
            approved_valid = False

        rendered: dict[str, bytes] = render_ledger(approved_set) if approved_valid else {}
        rerender_matches = (
            approved_valid
            and compute_input_hash(approved_set) == active["input_hash"]
            and compute_intended_output_hash(rendered) == intended_hash
        )

        # Classify the live tree.
        live_empty = _live_tree_empty(ledger_dir)
        live_hash = _live_tree_hash(ledger_dir, rendered) if rendered else None
        live_matches_intended = bool(rendered) and live_hash == intended_hash
        live_matches_prev = prev_hash is not None and rendered and live_hash == prev_hash

        # Row 1: pre-write abort. Nothing was written and staging never completed:
        # the live tree is empty or still holds the previous successful output.
        if not staging_ok and not live_matches_intended and (live_empty or live_matches_prev):
            fail_compile_run(conn, run_id, detail="aborted before writes", now_utc=now)
            return RecoveryDecision(
                action="marked_failed", compile_run_id=run_id, detail="Aborted before writes, marked failed"
            )

        # Deterministic recovery requires the approved set to still re-derive the
        # crashed run's frozen identity. If it does not (and this is not the clean
        # pre-write abort above), the live tree is in an unrecognized state.
        if not rerender_matches:
            append_compile_journal(conn, run_id, "refused", detail="live ledger in an unrecognized state", now_utc=now)
            append_audit_event(
                conn, actor="operator", action="compile recover", target=run_id,
                result="error", compile_run_id=run_id, ts_utc=now,
            )
            raise AmbiguousRecoveryError(
                "Approved set no longer re-derives the crashed run's intended output, and the live "
                "tree matches neither the previous successful output nor a recoverable staging copy."
            )

        # Row 4: genuine corruption — a non-empty live tree that matches neither the
        # previous output nor the intended output, with no intact staging to recover
        # from (a partial replace compounded by an external edit).
        if not staging_ok and not live_matches_intended and not live_matches_prev and not live_empty:
            append_compile_journal(conn, run_id, "refused", detail="live ledger in an unrecognized state", now_utc=now)
            append_audit_event(
                conn, actor="operator", action="compile recover", target=run_id,
                result="error", compile_run_id=run_id, ts_utc=now,
            )
            raise AmbiguousRecoveryError(
                "Live ledger matches neither the previous output nor the intended output, "
                "and no intact staging is present."
            )

        # Row 2: deterministic, re-entrant recovery. Write only files that differ.
        (ledger_dir / "txns").mkdir(parents=True, exist_ok=True)
        wrote_any = False
        order = ["accounts.beancount", "main.beancount"] + sorted(p for p in rendered if p.startswith("txns/"))
        for rel in order:
            dst = ledger_dir / rel
            want = rendered[rel]
            if dst.exists() and dst.read_bytes() == want:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_file(dst, want)  # write sibling temp + os.replace + fsync dir
            wrote_any = True

        # Drop any live txns/*.beancount not in the intended set (year removed).
        live_txns_dir = ledger_dir / "txns"
        if live_txns_dir.exists():
            intended_txns = {p for p in rendered if p.startswith("txns/")}
            for f in sorted(live_txns_dir.glob("*.beancount")):
                if f"txns/{f.name}" not in intended_txns:
                    f.unlink()
                    wrote_any = True

        # Sweep stale sibling temp files a crash may have left behind mid-replace.
        if _sweep_stale_temps(ledger_dir):
            wrote_any = True

        _fsync_dir(ledger_dir)

        if wrote_any:
            append_compile_journal(conn, run_id, "replaced", now_utc=now)

        actual_hash = _live_tree_hash(ledger_dir, rendered)
        if actual_hash != intended_hash:
            append_compile_journal(conn, run_id, "refused", detail="live ledger in an unrecognized state", now_utc=now)
            append_audit_event(
                conn, actor="operator", action="compile recover", target=run_id,
                result="error", compile_run_id=run_id, ts_utc=now,
            )
            raise AmbiguousRecoveryError(f"Post-write live hash {actual_hash} != intended {intended_hash}")

        # Idempotent finalize: safe to re-run even if the row is already 'recovered'.
        conn.execute(
            "UPDATE compile_runs SET status = 'recovered', actual_output_hash = ?, "
            "finished_at_utc = COALESCE(finished_at_utc, ?), recovery_state = 'recovered' "
            "WHERE compile_run_id = ? AND status != 'recovered'",
            (actual_hash, now, run_id),
        )
        conn.commit()
        append_compile_journal(conn, run_id, "recovered", now_utc=now)

        _replace_ledger_index(conn, run_id, approved_set, now)  # replace-not-append, idempotent

        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        append_audit_event(
            conn, actor="operator", action="compile", target=run_id, result="ok",
            compile_run_id=run_id, output_hash=actual_hash, ts_utc=now,
        )
        conn.commit()

        detail = (
            "Finished deterministic recovery" if wrote_any
            else "Recovery re-run: live tree already intact, finalized"
        )
        return RecoveryDecision(action="recovered", compile_run_id=run_id, detail=detail)
