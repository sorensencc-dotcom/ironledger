"""Normalize parsed rows to canonical records and write them as retained evidence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from ironledger.ingest.formats.model import ParsedRow

__all__ = ["normalize_row", "canonical_json", "write_source_record"]

_WS = re.compile(r"\s+")
_FIELD_ORDER = ("posted_date", "amount_text", "payee", "memo", "txn_type", "fitid", "currency")


def _canon_text(value: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", value)).strip()


def normalize_row(row: ParsedRow) -> dict[str, str]:
    """Return a canonical, order-fixed dict of NFC-normalized, whitespace-collapsed strings."""
    raw = {
        "posted_date": row.posted_date,
        "amount_text": row.amount_text,
        "payee": row.payee,
        "memo": row.memo,
        "txn_type": row.txn_type,
        "fitid": row.fitid,
        "currency": row.currency or "",
    }
    return {key: _canon_text(raw[key]) for key in _FIELD_ORDER}


def canonical_json(canonical: dict[str, str]) -> str:
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def write_source_record(
    conn: sqlite3.Connection,
    source_document_id: str,
    record_index: int,
    canonical: dict[str, str],
    *,
    records_dir: str | Path,
) -> str:
    """Insert a source_records row and write its canonical payload. Idempotent."""
    source_record_id = f"{source_document_id}:{record_index}"
    payload = canonical_json(canonical)
    content_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    existing = conn.execute(
        "SELECT source_record_id FROM source_records "
        "WHERE source_document_id = ? AND record_index = ?",
        (source_document_id, record_index),
    ).fetchone()
    if existing is not None:
        return existing[0]

    out_dir = Path(records_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{content_sha256}.json").write_text(payload, encoding="utf-8")

    now = _now_utc()
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
        " canonical_payload, content_sha256, created_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
        (source_record_id, source_document_id, record_index, payload, content_sha256, now),
    )
    return source_record_id


def _now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
