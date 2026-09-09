"""Write a staging projection SQLite file and manifest from a ParsedLedger."""

from __future__ import annotations

from pathlib import Path

from ironledger.compile.render import format_amount
from ironledger.db.connection import connect
from ironledger.manifests import generate_projection_manifest, render_manifest
from ironledger.project.errors import ProjectInputError
from ironledger.project.migrate import PROJECT_SCHEMA_VERSION, apply_schema
from ironledger.project.parse import ParsedAccount, ParsedLedger, ParsedPosting


def write_staging_projection(
    parsed: ParsedLedger,
    staging_dir: Path,
    *,
    compile_run_id: str,
    ledger_input_hash: str,
    ledger_output_hash: str,
    beancount_version: str,
    compiler_version: str,
    built_at_utc: str,
) -> Path:
    accounts = _unique_accounts(parsed)
    _refuse_posting_currency_mismatch(parsed, accounts)

    staging_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = staging_dir / "projection.sqlite"
    conn = connect(sqlite_path)
    try:
        apply_schema(conn)
        for acct in accounts.values():
            conn.execute(
                "INSERT INTO proj_accounts (account, currency, open_date) VALUES (?, ?, ?)",
                (acct.account, acct.currency, acct.open_date),
            )
        for entry in parsed.entries:
            conn.execute(
                "INSERT INTO proj_entries "
                "(entry_id, entry_date, payee, narration, staged_transaction_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    entry.entry_id,
                    entry.entry_date,
                    entry.payee,
                    entry.narration,
                    entry.staged_transaction_id,
                ),
            )
            for posting in entry.postings:
                conn.execute(
                    "INSERT INTO proj_postings ("
                    " posting_id, entry_id, account, minor_units, currency,"
                    " minor_unit_scale, source_document_id, source_record_id,"
                    " identity_algo_version, identity_method"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        posting.posting_id,
                        posting.entry_id,
                        posting.account,
                        posting.minor_units,
                        posting.currency,
                        posting.minor_unit_scale,
                        posting.source_document_id,
                        posting.source_record_id,
                        posting.identity_algo_version,
                        posting.identity_method,
                    ),
                )
        conn.execute(
            "INSERT INTO proj_balances "
            "SELECT account, currency, SUM(minor_units), MIN(minor_unit_scale) "
            "FROM proj_postings GROUP BY account, currency"
        )
        for entry in parsed.entries:
            for posting in entry.postings:
                conn.execute(
                    "INSERT INTO proj_fts "
                    "(payee, narration, account, posting_text, posting_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        entry.payee,
                        entry.narration,
                        posting.account,
                        _posting_text(posting),
                        posting.posting_id,
                    ),
                )
        conn.execute(
            "INSERT INTO projection_meta ("
            " singleton, compile_run_id, ledger_input_hash, ledger_output_hash,"
            " schema_version, built_at_utc, beancount_version, compiler_version"
            ") VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
            (
                compile_run_id,
                ledger_input_hash,
                ledger_output_hash,
                PROJECT_SCHEMA_VERSION,
                built_at_utc,
                beancount_version,
                compiler_version,
            ),
        )
        conn.commit()
        # Checkpoint before hashing so the main sqlite file contains every page.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        manifest = generate_projection_manifest(
            conn,
            compile_run_id=compile_run_id,
            ledger_input_hash=ledger_input_hash,
            output_hash=ledger_output_hash,
            db_path=sqlite_path,
            created_ts_utc=built_at_utc,
            schema_version=PROJECT_SCHEMA_VERSION,
        )
        (staging_dir / "projection.manifest.json").write_bytes(
            render_manifest(manifest).encode("utf-8")
        )
    finally:
        conn.close()
    return sqlite_path


def _unique_accounts(parsed: ParsedLedger) -> dict[str, ParsedAccount]:
    by_name: dict[str, ParsedAccount] = {}
    for acct in parsed.accounts:
        existing = by_name.get(acct.account)
        if existing is not None and existing.currency != acct.currency:
            raise ProjectInputError(
                f"account {acct.account} has currencies {existing.currency} and {acct.currency}"
            )
        if existing is None:
            by_name[acct.account] = acct
    return by_name


def _refuse_posting_currency_mismatch(
    parsed: ParsedLedger, accounts: dict[str, ParsedAccount]
) -> None:
    for entry in parsed.entries:
        for posting in entry.postings:
            opened = accounts.get(posting.account)
            if opened is not None and posting.currency != opened.currency:
                raise ProjectInputError(
                    f"posting {posting.posting_id} currency {posting.currency} "
                    f"does not match account {posting.account} currency {opened.currency}"
                )


def _posting_text(posting: ParsedPosting) -> str:
    formatted = format_amount(posting.minor_units, posting.minor_unit_scale)
    return (
        f"{posting.account} {formatted} {posting.currency} "
        f"{posting.identity_method} {posting.identity_algo_version}"
    )
