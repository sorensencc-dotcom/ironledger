"""Freshness check, FTS search, and balances against a live projection."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ironledger.compile.hashing import compute_actual_output_hash
from ironledger.db.connection import connect
from ironledger.manifests import ManifestError, parse_manifest, verify_manifest
from ironledger.project.errors import (
    ProjectInputError,
    ProjectStaleError,
    format_query_error,
    format_stale,
)
from ironledger.project.migrate import PROJECT_SCHEMA_VERSION
from ironledger.project.parse import discover_year_files

_SEARCH_LIMIT_MAX = 500


@dataclass(frozen=True)
class SearchHit:
    entry_date: str
    payee: str
    narration: str
    account: str
    minor_units: int
    currency: str
    staged_transaction_id: str
    posting_id: str


@dataclass(frozen=True)
class BalanceRow:
    account: str
    minor_units: int
    currency: str
    minor_unit_scale: int


def _stale(
    *,
    ledger_hash: str,
    projection_hash: str,
    ledger_dir: Path,
    db: str | None,
) -> ProjectStaleError:
    return ProjectStaleError(
        format_stale(
            ledger_hash=ledger_hash,
            projection_hash=projection_hash,
            ledger_dir=ledger_dir,
            db=db,
        )
    )


def assert_fresh(
    ledger_dir: Path,
    projection_dir: Path,
    *,
    db: str | None = None,
) -> sqlite3.Connection:
    ledger_dir = Path(ledger_dir)
    projection_dir = Path(projection_dir)
    sqlite_path = projection_dir / "projection.sqlite"
    manifest_path = projection_dir / "projection.manifest.json"
    ledger_hash = compute_actual_output_hash(ledger_dir, discover_year_files(ledger_dir))
    projection_hash = ""

    if not sqlite_path.is_file() or not manifest_path.is_file():
        raise _stale(
            ledger_hash=ledger_hash,
            projection_hash=projection_hash,
            ledger_dir=ledger_dir,
            db=db,
        )

    try:
        conn = connect(sqlite_path)
    except sqlite3.Error as exc:
        raise _stale(
            ledger_hash=ledger_hash,
            projection_hash=projection_hash,
            ledger_dir=ledger_dir,
            db=db,
        ) from exc

    try:
        row = conn.execute(
            "SELECT schema_version, ledger_output_hash FROM projection_meta WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise _stale(
                ledger_hash=ledger_hash,
                projection_hash=projection_hash,
                ledger_dir=ledger_dir,
                db=db,
            )
        schema_version, projection_hash = int(row[0]), str(row[1])
        manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
        verify_manifest(
            manifest,
            conn=conn,
            base_dir=projection_dir,
            schema_version=PROJECT_SCHEMA_VERSION,
        )
        if schema_version != PROJECT_SCHEMA_VERSION or projection_hash != ledger_hash:
            raise _stale(
                ledger_hash=ledger_hash,
                projection_hash=projection_hash,
                ledger_dir=ledger_dir,
                db=db,
            )
    except ProjectStaleError:
        conn.close()
        raise
    except (ManifestError, sqlite3.Error, OSError, UnicodeDecodeError) as exc:
        conn.close()
        raise _stale(
            ledger_hash=ledger_hash,
            projection_hash=projection_hash,
            ledger_dir=ledger_dir,
            db=db,
        ) from exc
    except Exception:
        conn.close()
        raise
    return conn


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[SearchHit]:
    if not query.strip():
        raise ProjectInputError(format_query_error("empty search query"))
    if limit < 1 or limit > _SEARCH_LIMIT_MAX:
        raise ProjectInputError("limit must be between 1 and 500")
    if offset < 0:
        raise ProjectInputError("offset must not be negative")
    sql = (
        "SELECT e.entry_date, e.payee, e.narration, p.account, p.minor_units, "
        "p.currency, e.staged_transaction_id, p.posting_id "
        "FROM proj_fts "
        "JOIN proj_postings AS p ON p.posting_id = proj_fts.posting_id "
        "JOIN proj_entries AS e ON e.entry_id = p.entry_id "
        "WHERE proj_fts MATCH ? "
        "ORDER BY e.entry_date ASC, p.posting_id ASC "
        "LIMIT ? OFFSET ?"
    )
    try:
        rows = conn.execute(sql, (query, limit, offset)).fetchall()
    except sqlite3.OperationalError as exc:
        raise ProjectInputError(format_query_error("invalid FTS query")) from exc
    return [
        SearchHit(
            entry_date=row[0],
            payee=row[1],
            narration=row[2],
            account=row[3],
            minor_units=row[4],
            currency=row[5],
            staged_transaction_id=row[6],
            posting_id=row[7],
        )
        for row in rows
    ]


def balances(conn: sqlite3.Connection) -> list[BalanceRow]:
    rows = conn.execute(
        "SELECT account, minor_units, currency, minor_unit_scale "
        "FROM proj_balances ORDER BY account ASC, currency ASC"
    ).fetchall()
    return [
        BalanceRow(
            account=row[0],
            minor_units=row[1],
            currency=row[2],
            minor_unit_scale=row[3],
        )
        for row in rows
    ]
