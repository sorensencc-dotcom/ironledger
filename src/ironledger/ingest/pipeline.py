"""Single-threaded orchestration: acquire, parse, normalize, identify, stage, audit."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ironledger.audit import append_audit_event
from ironledger.conventions import currency_scale
from ironledger.ingest.acquire import acquire
from ironledger.ingest.errors import IngestError, ParseError
from ironledger.ingest.formats.csv_engine import load_profile, parse_csv
from ironledger.ingest.formats.model import ParsedFile, institution_account_key
from ironledger.ingest.formats.ofx import parse_ofx
from ironledger.ingest.identity import fingerprint, select_identity_method
from ironledger.ingest.records import normalize_row, write_source_record
from ironledger.ingest.stage import StagedInput, minor_units_from_text, upsert_staged

__all__ = ["ImportResult", "run_import"]


@dataclass(frozen=True)
class ImportResult:
    source_document_id: str
    records_created: int
    short_circuited: bool
    advisories: tuple[str, ...]


def _parse(resolved_path: Path, csv_profile: str | None, config_dir: Path) -> ParsedFile:
    suffix = resolved_path.suffix.lower()
    if suffix in (".ofx", ".qfx"):
        return parse_ofx(resolved_path.read_bytes())
    if suffix == ".csv":
        if not csv_profile:
            raise ParseError("a CSV import needs --csv-profile")
        profile = load_profile(config_dir, csv_profile)
        return parse_csv(resolved_path.read_bytes(), profile)
    raise ParseError(f"unsupported file type {suffix!r}")


def _all_rows_staged(conn: sqlite3.Connection, source_document_id: str, expected_rows: int) -> bool:
    staged = conn.execute(
        "SELECT count(*) FROM staged_transactions st "
        "JOIN source_records sr ON sr.source_record_id = st.source_record_id "
        "WHERE sr.source_document_id = ?",
        (source_document_id,),
    ).fetchone()[0]
    return staged >= expected_rows


def run_import(
    conn: sqlite3.Connection,
    resolved_path: Path,
    *,
    config_dir: Path,
    evidence_dir: Path,
    records_dir: Path,
    csv_profile: str | None = None,
    allow_partial: bool = False,
    actor: str = "operator",
    now_utc: str | None = None,
) -> ImportResult:
    resolved_path = Path(resolved_path)
    # spec §8: an authorized import invocation always emits exactly one audit
    # event. A single outer handler covers parse + acquire + the row loop so
    # an IngestError raised before `acquire` still audits once (target keyed to
    # the file) and every partial write is rolled back.
    doc_id: str | None = None
    try:
        parsed = _parse(resolved_path, csv_profile, Path(config_dir))
        provenance = institution_account_key(parsed)
        advisories: list[str] = []

        acq = acquire(
            conn, resolved_path, evidence_dir=Path(evidence_dir),
            provenance=provenance, now_utc=now_utc,
        )
        doc_id = acq.source_document_id

        if not acq.is_new and _all_rows_staged(conn, acq.source_document_id, len(parsed.rows)):
            _audit(conn, actor, acq.source_document_id, "ok", now_utc, note="records_created=0")
            conn.commit()
            return ImportResult(acq.source_document_id, 0, short_circuited=True, advisories=())

        if parsed.account is None:
            # OFX/QFX: the imported account name is not yet mapped. Phase 2a uses a
            # deterministic placeholder derived from the account id; Phase 2b review
            # assigns the real account. The placeholder is a valid five-root name.
            parsed = _with_placeholder_account(parsed)

        if any(r.fitid for r in parsed.rows):
            method_probe = select_identity_method(
                conn, parsed.institution_id, parsed.account_id, has_fitid=True
            )
            if method_probe == "sha256_fallback":
                advisories.append(
                    f"advisory: {parsed.institution_id}/{parsed.account_id} carries FITIDs but is "
                    f"not trusted. Run: ironledger fitid-trust add --institution "
                    f"{parsed.institution_id} --account {parsed.account_id}  before the first import "
                    f"of this account to use FITID identity."
                )

        created = 0
        for index, row in enumerate(parsed.rows):
            scale = currency_scale(row.currency or parsed.default_currency)
            currency = row.currency or parsed.default_currency
            minor_units = minor_units_from_text(row.amount_text, scale)
            canonical = normalize_row(row)
            source_record_id = write_source_record(
                conn, acq.source_document_id, index, canonical, records_dir=Path(records_dir)
            )
            method = select_identity_method(
                conn, parsed.institution_id, parsed.account_id, has_fitid=bool(row.fitid)
            )
            fp = fingerprint(
                account=parsed.account,
                iso_date=row.posted_date,
                minor_units=minor_units,
                currency=currency,
                payee=row.payee,
                institution_account_key=provenance,
            )
            _stx_id, was_created = upsert_staged(
                conn,
                StagedInput(
                    source_record_id=source_record_id,
                    account=parsed.account,
                    iso_date=row.posted_date,
                    minor_units=minor_units,
                    currency=currency,
                    scale=scale,
                    payee=row.payee,
                    fitid=row.fitid,
                    identity_method=method,
                    identity_fingerprint=fp,
                    institution_account_key=provenance,
                ),
                now_utc=now_utc,
            )
            if was_created:
                created += 1

        _audit(conn, actor, acq.source_document_id, "ok", now_utc, note=f"records_created={created}")
        conn.commit()
        return ImportResult(acq.source_document_id, created, short_circuited=False, advisories=tuple(advisories))
    except IngestError:
        # Discards every partial source_records / staged_transactions / staged_postings
        # write for this file. Harmless when nothing was written yet (parse-time failure).
        conn.rollback()
        target = doc_id if doc_id is not None else f"import:{resolved_path.name}"
        _audit(conn, actor, target, "error", now_utc)
        conn.commit()
        raise


def _with_placeholder_account(parsed: ParsedFile) -> ParsedFile:
    from dataclasses import replace

    safe = "".join(ch for ch in parsed.account_id if ch.isalnum()) or "Unmapped"
    return replace(parsed, account=f"Assets:Unmapped:{safe[:32]}")


def _audit(conn, actor, target, result, now_utc, *, note: str | None = None) -> None:
    append_audit_event(
        conn,
        actor=actor,
        action="import" if note is None else f"import ({note})",
        target=target,
        result=result,
        ts_utc=now_utc,
    )
