from __future__ import annotations

from pathlib import Path

from ironledger.compile.hashing import compute_actual_output_hash
from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction
from ironledger.compile.render import render_ledger
from ironledger.db import migrations
from ironledger.db.connection import connect


def make_sample_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        staged_posting_id="sp-1", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="imported", posting_index=0, account="Assets:Checking",
        minor_units=-1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f" * 64,
    )
    p2 = ApprovedPosting(
        staged_posting_id="sp-2", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="contra", posting_index=1, account="Expenses:Food",
        minor_units=1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f" * 64,
    )
    t1 = ApprovedTransaction(
        staged_transaction_id="stx-1", source_record_id="rec-1", source_document_id="doc-1",
        proposed_date="2026-09-01", payee='Coffee "Shop"\\Cafe', narration="Latte",
        identity_algo_version=1, identity_method="fitid", identity_fingerprint="f" * 64,
        postings=(p1, p2),
    )
    return ApprovedSet(transactions=(t1,))


def make_jpy_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        "sp-j1", "stx-jpy", "rec-1", "doc-1", "imported", 0, "Assets:Cash",
        -100, "JPY", 0, 1, "fitid", "e" * 64,
    )
    p2 = ApprovedPosting(
        "sp-j2", "stx-jpy", "rec-1", "doc-1", "contra", 1, "Expenses:Food",
        100, "JPY", 0, 1, "fitid", "e" * 64,
    )
    t1 = ApprovedTransaction(
        "stx-jpy", "rec-1", "doc-1", "2026-09-02", "Tokyo Cafe", "Yen",
        1, "fitid", "e" * 64, (p1, p2),
    )
    return ApprovedSet(transactions=(t1,))


def write_ledger(ledger_dir: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = ledger_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def write_rendered_ledger(ledger_dir: Path, approved_set: ApprovedSet | None = None) -> dict[str, bytes]:
    if approved_set is None:
        approved_set = make_sample_set()
    files = render_ledger(approved_set)
    write_ledger(ledger_dir, files)
    return files


def seed_successful_compile_run(db_path: Path, ledger_dir: Path, compile_run_id: str = "run-1") -> str:
    year_files = [f"txns/{p.name}" for p in sorted((ledger_dir / "txns").glob("*.beancount"))]
    actual = compute_actual_output_hash(ledger_dir, year_files)
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, actual_output_hash, status, started_at_utc, "
        " finished_at_utc, recovery_state) "
        "VALUES (?, '3.2.3', '0.1.0', ?, ?, ?, 'succeeded', "
        " '2026-09-08T12:00:00Z', '2026-09-08T12:00:01Z', 'none')",
        (compile_run_id, "a" * 64, actual, actual),
    )
    conn.commit()
    conn.close()
    return actual
