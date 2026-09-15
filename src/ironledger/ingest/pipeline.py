"""Single-threaded orchestration: acquire, parse, normalize, identify, stage, audit."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

from datetime import datetime, timezone

from ironledger.audit import append_audit_event
from ironledger.conventions import (
    ConventionError,
    currency_scale,
    validate_account_name,
    validate_currency,
)
from ironledger.ingest.acquire import acquire
from ironledger.ingest.errors import IngestError, ParseError
from ironledger.ingest.attach import assign_proposals
from ironledger.ingest.formats.csv_engine import load_profile, parse_csv
from ironledger.ingest.formats.model import ParsedFile, institution_account_key
from ironledger.ingest.formats.ofx import parse_ofx
from ironledger.ingest.formats.pdf_engine import load_pdf_profile, parse_pdf
from ironledger.ingest.identity import canonical_payee, fingerprint, select_identity_method
from ironledger.ingest.records import normalize_row, write_source_record
from ironledger.ingest.stage import StagedInput, minor_units_from_text, upsert_staged
from ironledger.review.rules import resolve_rule

__all__ = ["ImportResult", "run_import"]


@dataclass(frozen=True)
class ImportResult:
    source_document_id: str
    records_created: int
    short_circuited: bool
    advisories: tuple[str, ...]


def _parse(
    resolved_path: Path,
    csv_profile: str | None,
    pdf_profile: str | None,
    config_dir: Path,
) -> tuple[ParsedFile, int]:
    suffix = resolved_path.suffix.lower()
    if suffix in (".ofx", ".qfx"):
        return parse_ofx(resolved_path.read_bytes()), 3
    if suffix == ".csv":
        if not csv_profile:
            raise ParseError("a CSV import needs --csv-profile")
        if pdf_profile:
            raise ParseError("--pdf-profile is rejected for CSV")
        profile = load_profile(config_dir, csv_profile)
        return parse_csv(resolved_path.read_bytes(), profile), 3
    if suffix == ".pdf":
        if not pdf_profile:
            raise ParseError("a PDF import needs --pdf-profile")
        if csv_profile:
            raise ParseError("--csv-profile is rejected for PDF")
        profile = load_pdf_profile(config_dir, pdf_profile)
        return parse_pdf(resolved_path.read_bytes(), profile), profile.date_window_days
    raise ParseError(f"unsupported file type {suffix!r}")


def _all_rows_accounted(
    conn: sqlite3.Connection, source_document_id: str, expected_rows: int
) -> bool:
    accounted = conn.execute(
        "SELECT count(*) FROM source_records sr "
        "WHERE sr.source_document_id = ? AND ("
        " EXISTS (SELECT 1 FROM staged_transactions st "
        "         WHERE st.source_record_id = sr.source_record_id) "
        " OR EXISTS (SELECT 1 FROM attach_proposals ap "
        "            WHERE ap.source_record_id = sr.source_record_id "
        "              AND ap.status IN ('pending', 'confirmed'))"
        ")",
        (source_document_id,),
    ).fetchone()[0]
    return accounted >= expected_rows


def run_import(
    conn: sqlite3.Connection,
    resolved_path: Path,
    *,
    config_dir: Path,
    evidence_dir: Path,
    records_dir: Path,
    csv_profile: str | None = None,
    pdf_profile: str | None = None,
    importing_account: str | None = None,
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
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        parsed, date_window_days = _parse(
            resolved_path, csv_profile, pdf_profile, Path(config_dir)
        )
        provenance = institution_account_key(parsed)
        advisories: list[str] = []

        acq = acquire(
            conn, resolved_path, evidence_dir=Path(evidence_dir),
            provenance=provenance, now_utc=now_utc,
        )
        doc_id = acq.source_document_id

        if not acq.is_new and _all_rows_accounted(
            conn, acq.source_document_id, len(parsed.rows)
        ):
            _audit(
                conn, actor, acq.source_document_id, "ok", now_utc,
                note="records_created=0, rules_applied=0",
            )
            conn.commit()
            return ImportResult(acq.source_document_id, 0, short_circuited=True, advisories=())

        if parsed.account is None and importing_account is None:
            raise ParseError("an OFX or QFX import needs --importing-account")
        if parsed.account is not None and importing_account is not None:
            raise ParseError(
                "--importing-account is only for OFX/QFX; a CSV import takes its account from the profile"
            )
        if parsed.account is None:
            try:
                parsed = replace(parsed, account=validate_account_name(importing_account))
            except ConventionError as exc:
                raise ParseError(f"--importing-account: {exc}") from exc

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

        import_account = parsed.account
        created = 0
        rules_applied = 0
        pending: list[tuple[StagedInput, int, str | None]] = []
        for index, row in enumerate(parsed.rows):
            raw_currency = row.currency or parsed.default_currency
            # spec §10: a currency that cannot be resolved to a valid ISO-4217
            # code must surface as a ParseError inside this outer try (the CSV
            # path pre-validates; the OFX <CURDEF>/per-row path does not), so the
            # handler rolls back, writes exactly one error audit, and the CLI
            # returns exit 4 instead of an unhandled ConventionError/TypeError.
            try:
                currency = validate_currency(raw_currency) if raw_currency else None
                if currency is None:
                    raise ParseError(f"row {index}: no resolvable currency", row_index=index)
                scale = currency_scale(currency)
            except ConventionError as exc:
                raise ParseError(
                    f"row {index}: currency {raw_currency!r}: {exc}", row_index=index
                ) from exc
            minor_units = minor_units_from_text(row.amount_text, scale)
            canonical = normalize_row(row)
            source_record_id = write_source_record(
                conn, acq.source_document_id, index, canonical, records_dir=Path(records_dir)
            )
            method = select_identity_method(
                conn, parsed.institution_id, parsed.account_id, has_fitid=bool(row.fitid)
            )
            fp = fingerprint(
                account=import_account,
                iso_date=row.posted_date,
                minor_units=minor_units,
                currency=currency,
                payee=row.payee,
                institution_account_key=provenance,
            )
            contra_account = resolve_rule(
                conn, canonical_payee(row.payee), import_account, now_utc=now_utc
            )
            pending.append(
                (
                    StagedInput(
                        source_record_id=source_record_id,
                        account=import_account,
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
                    date_window_days,
                    contra_account,
                )
            )

        assign_proposals(
            conn,
            source_document_id=acq.source_document_id,
            rows=tuple((staged, window) for staged, window, _contra in pending),
            now_utc=now_utc,
        )
        proposed = {
            rec for (rec,) in conn.execute(
                "SELECT source_record_id FROM attach_proposals "
                "WHERE source_document_id = ? AND status = 'pending'",
                (acq.source_document_id,),
            )
        }
        for staged, _window, contra_account in pending:
            if staged.source_record_id in proposed:
                continue
            _stx_id, was_created = upsert_staged(
                conn, staged, now_utc=now_utc, contra_account=contra_account,
            )
            if was_created:
                created += 1
                if contra_account is not None:
                    rules_applied += 1

        _audit(
            conn, actor, acq.source_document_id, "ok", now_utc,
            note=f"records_created={created}, rules_applied={rules_applied}",
        )
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
    except sqlite3.Error as exc:
        conn.rollback()
        target = doc_id if doc_id is not None else f"import:{resolved_path.name}"
        _audit(conn, actor, target, "error", now_utc)
        conn.commit()
        raise ParseError(f"import failed a database constraint: {exc}") from exc


def _audit(conn, actor, target, result, now_utc, *, note: str | None = None) -> None:
    append_audit_event(
        conn,
        actor=actor,
        action="import" if note is None else f"import ({note})",
        target=target,
        result=result,
        ts_utc=now_utc,
    )
