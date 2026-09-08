"""Tests for input and output hash stability and verification."""

from __future__ import annotations

import tempfile
from pathlib import Path
from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction
from ironledger.compile.render import render_ledger
from ironledger.compile.hashing import (
    compute_input_hash,
    compute_intended_output_hash,
    compute_actual_output_hash,
)


def _sample_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        staged_posting_id="sp-1", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="imported", posting_index=0, account="Assets:Checking",
        minor_units=-1000, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="1"*64
    )
    p2 = ApprovedPosting(
        staged_posting_id="sp-2", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="contra", posting_index=1, account="Expenses:Food",
        minor_units=1000, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="1"*64
    )
    t1 = ApprovedTransaction(
        staged_transaction_id="stx-1", source_record_id="rec-1", source_document_id="doc-1",
        proposed_date="2026-09-01", payee="Grocer", narration="", identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="1"*64, postings=(p1, p2)
    )
    return ApprovedSet(transactions=(t1,))


def test_input_hash_is_stable_and_sha256():
    app_set = _sample_set()
    h1 = compute_input_hash(app_set)
    h2 = compute_input_hash(app_set)
    assert h1 == h2
    assert len(h1) == 64
    assert h1.islower()


def test_intended_hash_matches_disk_hash():
    app_set = _sample_set()
    files = render_ledger(app_set)
    intended_hash = compute_intended_output_hash(files)

    with tempfile.TemporaryDirectory() as tmpdir:
        ldir = Path(tmpdir)
        (ldir / "txns").mkdir(parents=True)
        for rel_path, content in files.items():
            fpath = ldir / rel_path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_bytes(content)

        year_files = [p for p in files.keys() if p.startswith("txns/")]
        disk_hash = compute_actual_output_hash(ldir, year_files)
        assert disk_hash == intended_hash
