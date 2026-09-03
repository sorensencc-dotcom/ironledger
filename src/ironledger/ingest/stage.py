"""Write the staged_transactions header and its two proposed postings. Idempotent."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from ironledger.ingest.errors import ParseError, StageError
from ironledger.ingest.identity import IDENTITY_ALGO_VERSION

__all__ = ["StagedInput", "minor_units_from_text", "upsert_staged"]

_PLAIN_DECIMAL = re.compile(r"\A(?P<sign>-?)(?P<whole>\d+)(?:\.(?P<frac>\d+))?\Z")


@dataclass(frozen=True)
class StagedInput:
    source_record_id: str
    account: str
    iso_date: str
    minor_units: int
    currency: str
    scale: int
    payee: str
    fitid: str
    identity_method: str
    identity_fingerprint: str
    institution_account_key: str


def minor_units_from_text(amount_text: str, scale: int) -> int:
    """Convert a plain decimal string to signed integer minor units, exactly."""
    match = _PLAIN_DECIMAL.match(amount_text.strip())
    if match is None:
        raise ParseError(f"amount {amount_text!r} is not a plain decimal")
    frac = match.group("frac") or ""
    if len(frac) > scale:
        raise ParseError(
            f"amount {amount_text!r} has {len(frac)} fractional digits; currency scale is {scale}"
        )
    frac_padded = (frac + "0" * scale)[:scale]
    magnitude = int(match.group("whole") + frac_padded) if scale else int(match.group("whole"))
    return -magnitude if match.group("sign") == "-" else magnitude


def upsert_staged(
    conn: sqlite3.Connection,
    staged: StagedInput,
    *,
    now_utc: str | None = None,
) -> tuple[str, bool]:
    existing = conn.execute(
        "SELECT staged_transaction_id FROM staged_transactions "
        "WHERE identity_algo_version = ? AND identity_fingerprint = ?",
        (IDENTITY_ALGO_VERSION, staged.identity_fingerprint),
    ).fetchone()
    if existing is not None:
        return existing[0], False

    ts = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stx_id = f"stx:{staged.identity_fingerprint}"
    try:
        conn.execute(
            "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, "
            " proposed_date, payee, narration, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES (?, ?, 'pending', ?, ?, '', ?, ?, ?, ?)",
            (
                stx_id,
                staged.source_record_id,
                staged.iso_date,
                staged.payee,
                IDENTITY_ALGO_VERSION,
                staged.identity_method,
                staged.identity_fingerprint,
                ts,
            ),
        )
        conn.executemany(
            "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, "
            " role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f"{stx_id}:0", stx_id, staged.source_record_id, "imported", 0,
                 staged.account, staged.minor_units, staged.currency, staged.scale, ts),
                (f"{stx_id}:1", stx_id, staged.source_record_id, "contra", 1,
                 None, -staged.minor_units, staged.currency, staged.scale, ts),
            ],
        )
    except sqlite3.IntegrityError as exc:
        raise StageError(f"staging {stx_id} violated a constraint: {exc}") from exc
    return stx_id, True
