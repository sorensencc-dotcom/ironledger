"""Tests for deterministic pure-function Beancount ledger rendering."""

from __future__ import annotations

import pytest
from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction
from ironledger.compile.render import render_ledger, format_amount, escape_beancount_string


def _make_sample_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        staged_posting_id="sp-1", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="imported", posting_index=0, account="Assets:Checking",
        minor_units=-1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f"*64
    )
    p2 = ApprovedPosting(
        staged_posting_id="sp-2", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="contra", posting_index=1, account="Expenses:Food",
        minor_units=1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f"*64
    )
    t1 = ApprovedTransaction(
        staged_transaction_id="stx-1", source_record_id="rec-1", source_document_id="doc-1",
        proposed_date="2026-09-01", payee='Coffee "Shop"\\Cafe', narration="Latte",
        identity_algo_version=1, identity_method="fitid", identity_fingerprint="f"*64,
        postings=(p1, p2)
    )
    return ApprovedSet(transactions=(t1,))


def test_format_amount_various_scales():
    assert format_amount(-1234, 2) == "-12.34"
    assert format_amount(1234, 2) == "12.34"
    assert format_amount(50, 2) == "0.50"
    assert format_amount(5, 2) == "0.05"
    assert format_amount(100, 0) == "100"
    assert format_amount(-5, 3) == "-0.005"


def test_escape_beancount_string():
    assert escape_beancount_string('Coffee "Shop"\\Cafe') == 'Coffee \\"Shop\\"\\\\Cafe'


def test_render_ledger_deterministic_output():
    app_set = _make_sample_set()
    files1 = render_ledger(app_set)
    files2 = render_ledger(app_set)
    assert files1 == files2

    assert "main.beancount" in files1
    assert "accounts.beancount" in files1
    assert "txns/2026.beancount" in files1

    main_text = files1["main.beancount"].decode("utf-8")
    assert 'option "title" "IronLedger"' in main_text
    assert 'option "operating_currency" "USD"' in main_text
    assert 'include "accounts.beancount"' in main_text
    assert 'include "txns/2026.beancount"' in main_text

    accounts_text = files1["accounts.beancount"].decode("utf-8")
    assert "2026-09-01 open Assets:Checking USD\n2026-09-01 open Expenses:Food USD\n" == accounts_text

    tx_text = files1["txns/2026.beancount"].decode("utf-8")
    assert '2026-09-01 * "Coffee \\"Shop\\"\\\\Cafe" "Latte"' in tx_text
    assert '  staged-transaction-id: "stx-1"' in tx_text
    assert '  Assets:Checking  -12.34 USD' in tx_text
    assert '    source-document-id: "doc-1"' in tx_text
    assert '  Expenses:Food  12.34 USD' in tx_text
