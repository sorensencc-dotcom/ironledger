"""Versioned canonical identity for Phase 2a. Algorithm version 1 is frozen."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata

__all__ = [
    "IDENTITY_ALGO_VERSION",
    "canonical_payee",
    "fingerprint",
    "select_identity_method",
]

IDENTITY_ALGO_VERSION = 1

_WS = re.compile(r"\s+")


def canonical_payee(value: str) -> str:
    """NFC, then casefold, then ASCII whitespace collapse, then strip. Order frozen for v1."""
    folded = unicodedata.normalize("NFC", value).casefold()
    return _WS.sub(" ", folded).strip()


def fingerprint(
    *,
    account: str,
    iso_date: str,
    minor_units: int,
    currency: str,
    payee: str,
    institution_account_key: str,
) -> str:
    """SHA-256 over the canonical v1 identity tuple."""
    tuple_repr = json.dumps(
        [
            IDENTITY_ALGO_VERSION,
            account,
            iso_date,
            minor_units,
            currency,
            canonical_payee(payee),
            institution_account_key,
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(tuple_repr.encode("utf-8")).hexdigest()


def select_identity_method(
    conn: sqlite3.Connection,
    institution_id: str,
    account_id: str,
    *,
    has_fitid: bool,
) -> str:
    """Return 'fitid' only when the pair is trusted and the record carries a FITID."""
    if not has_fitid:
        return "sha256_fallback"
    row = conn.execute(
        "SELECT 1 FROM fitid_trust_records WHERE institution_id = ? AND account_id = ?",
        (institution_id, account_id),
    ).fetchone()
    return "fitid" if row is not None else "sha256_fallback"
