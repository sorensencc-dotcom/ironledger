from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from ironledger.compile.model import ApprovedSet

INPUT_HASH_ALGO_VERSION: Final[int] = 1


def compute_input_hash(approved_set: ApprovedSet) -> str:
    records = []
    for tx in approved_set.transactions:
        postings_data = []
        for p in tx.postings:
            postings_data.append({
                "posting_id": p.staged_posting_id,
                "role": p.role,
                "account": p.account,
                "minor_units": p.minor_units,
                "currency": p.currency,
                "minor_unit_scale": p.minor_unit_scale,
                "source_record_id": p.source_record_id,
                "source_document_id": p.source_document_id,
                "identity_algo_version": p.identity_algo_version,
                "identity_method": p.identity_method,
            })
        records.append({
            "staged_transaction_id": tx.staged_transaction_id,
            "proposed_date": tx.proposed_date,
            "payee": tx.payee,
            "narration": tx.narration,
            "identity_algo_version": tx.identity_algo_version,
            "identity_method": tx.identity_method,
            "identity_fingerprint": tx.identity_fingerprint,
            "postings": postings_data,
        })
    payload = {
        "version": INPUT_HASH_ALGO_VERSION,
        "transactions": records,
    }
    # Finding 5: every kwarg here is load-bearing for a stable digest across Python
    # patch releases and locales — sort_keys, fixed separators, ensure_ascii. Do not relax.
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_intended_output_hash(files: dict[str, bytes]) -> str:
    hasher = hashlib.sha256()
    hasher.update(files.get("main.beancount", b""))
    hasher.update(files.get("accounts.beancount", b""))
    year_paths = sorted([p for p in files.keys() if p.startswith("txns/")])
    for yp in year_paths:
        hasher.update(files[yp])
    return hasher.hexdigest()


def compute_actual_output_hash(ledger_dir: Path, year_files: list[str]) -> str:
    hasher = hashlib.sha256()
    main_path = ledger_dir / "main.beancount"
    hasher.update(main_path.read_bytes() if main_path.exists() else b"")

    acct_path = ledger_dir / "accounts.beancount"
    hasher.update(acct_path.read_bytes() if acct_path.exists() else b"")

    for yf in sorted(year_files):
        yp = ledger_dir / yf
        hasher.update(yp.read_bytes() if yp.exists() else b"")
    return hasher.hexdigest()
