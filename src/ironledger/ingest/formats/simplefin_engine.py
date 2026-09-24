"""SimpleFIN feed parser, amount normalizer, and DB-enforced deduplication for Phase 7."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from ironledger.ingest.errors import ParseError

__all__ = ["parse_amount", "simplefin_external_id", "ingest_simplefin_payload"]

_AMOUNT_GRAMMAR = re.compile(r"^[+-]?\d+(\.\d{1,2})?$")
_FALLBACK_PREFIX = "Assets:Unassigned:SimpleFIN-"


def parse_amount(amount_str: str) -> int:
    r"""Convert SimpleFIN amount string to signed integer cents.

    Formula: sign * (dollars * 100 + cents).
    Grammar: ^[+-]?\d+(\.\d{1,2})?$
    """
    if not _AMOUNT_GRAMMAR.match(amount_str):
        raise ParseError(f"amount {amount_str!r} does not match SimpleFIN grammar")
    negative = amount_str.startswith("-")
    clean = amount_str.lstrip("+-")
    if "." in clean:
        whole_str, frac_str = clean.split(".", 1)
        frac_padded = (frac_str + "00")[:2]
    else:
        whole_str, frac_padded = clean, "00"
    magnitude = int(whole_str) * 100 + int(frac_padded)
    return -magnitude if negative else magnitude


def simplefin_external_id(
    account_id: str,
    tx_id: str | None,
    *,
    posted_date: str,
    amount_cents: int,
    currency: str,
    description: str,
    memo: str,
) -> str:
    """Return account-scoped primary ID or composite:v1 fallback."""
    if tx_id:
        return f"simplefin:id:{account_id}:{tx_id}"
    canonical = json.dumps(
        [account_id, posted_date, amount_cents, currency, description, memo],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"composite:v1:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _iso_from_unix(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def ingest_simplefin_payload(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    evidence_path: Path,
    account_map: dict[str, str],
) -> tuple[int, int]:
    """Stage all transactions in payload. Returns (inserted, skipped).

    Runs inside BEGIN IMMEDIATE. Uses ON CONFLICT(external_id) WHERE external_id IS NOT NULL DO NOTHING
    for deduplication.
    """
    inserted = skipped = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        for account in payload.get("accounts", []):
            acct_id = account["id"]
            currency = account.get("currency", "USD")
            canonical_account = account_map.get(acct_id, f"{_FALLBACK_PREFIX}{acct_id}")
            for tx in account.get("transactions", []):
                tx_id = tx.get("id") or None
                posted = _iso_from_unix(int(tx["posted"]))
                cents = parse_amount(str(tx["amount"]))
                desc = tx.get("description") or ""
                memo = tx.get("memo", "") or ""
                ext_id = simplefin_external_id(
                    acct_id,
                    tx_id,
                    posted_date=posted,
                    amount_cents=cents,
                    currency=currency,
                    description=desc,
                    memo=memo,
                )
                fp = hashlib.sha256(ext_id.encode()).hexdigest()
                src_doc_id = f"simplefin:{ext_id}"
                doc_hash = hashlib.sha256(src_doc_id.encode()).hexdigest()
                conn.execute(
                    "INSERT OR IGNORE INTO source_documents "
                    "(source_document_id,mime_type,encoding,provenance,"
                    "acquisition_time_utc,content_sha256,raw_payload_ref,created_at_utc) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        src_doc_id,
                        "application/json",
                        "utf-8",
                        f"simplefin:{acct_id}",
                        now,
                        doc_hash,
                        str(evidence_path),
                        now,
                    ),
                )
                src_rec_id = f"sr:{ext_id}"
                tx_json = json.dumps(tx, separators=(",", ":"))
                tx_hash = hashlib.sha256(tx_json.encode()).hexdigest()
                conn.execute(
                    "INSERT OR IGNORE INTO source_records "
                    "(source_record_id,source_document_id,record_index,"
                    "canonical_payload,content_sha256,created_at_utc) VALUES (?,?,0,?,?,?)",
                    (src_rec_id, src_doc_id, tx_json, tx_hash, now),
                )
                stx_id = f"stx:{ext_id}"
                r = conn.execute(
                    "INSERT INTO staged_transactions "
                    "(staged_transaction_id,source_record_id,status,proposed_date,payee,"
                    "narration,identity_algo_version,identity_method,identity_fingerprint,"
                    "external_id,created_at_utc) "
                    "VALUES (?,?,'pending',?,?,'',1,'fitid',?,?,?) "
                    "ON CONFLICT(external_id) WHERE external_id IS NOT NULL DO NOTHING",
                    (stx_id, src_rec_id, posted, desc, fp, ext_id, now),
                )
                if r.rowcount == 1:
                    conn.executemany(
                        "INSERT OR IGNORE INTO staged_postings "
                        "(staged_posting_id,staged_transaction_id,source_record_id,"
                        "role,posting_index,account,minor_units,currency,minor_unit_scale,created_at_utc) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [
                            (
                                f"{stx_id}:0",
                                stx_id,
                                src_rec_id,
                                "imported",
                                0,
                                canonical_account,
                                cents,
                                currency,
                                2,
                                now,
                            ),
                            (
                                f"{stx_id}:1",
                                stx_id,
                                src_rec_id,
                                "contra",
                                1,
                                "Expenses:Unassigned",
                                -cents,
                                currency,
                                2,
                                now,
                            ),
                        ],
                    )
                    inserted += 1
                else:
                    skipped += 1
    return inserted, skipped
