from __future__ import annotations

import pytest

from ironledger.compile.model import (
    ApprovedPosting,
    ApprovedSet,
    ApprovedTransaction,
    CompileInputError,
    validate_approved_set,
)
from ironledger.compile.render import render_ledger


def make_posting(
    role: str,
    account: str | None,
    minor_units: int,
    currency: str = "USD",
    scale: int = 2,
    doc_id: str = "doc_1",
    rec_id: str = "rec_1",
    posting_index: int = 0,
    stx_id: str = "stx_1",
) -> ApprovedPosting:
    return ApprovedPosting(
        staged_posting_id=f"sp_{stx_id}_{posting_index}",
        staged_transaction_id=stx_id,
        source_record_id=rec_id,
        source_document_id=doc_id,
        role=role,
        posting_index=posting_index,
        account=account,
        minor_units=minor_units,
        currency=currency,
        minor_unit_scale=scale,
        identity_algo_version=1,
        identity_method="exact",
        identity_fingerprint="fp_post",
    )


def test_compile_multileg_3_contra_legs_valid():
    tx = ApprovedTransaction(
        staged_transaction_id="stx_split_001",
        source_document_id="doc_1",
        source_record_id="rec_parent",
        proposed_date="2026-09-29",
        payee="Amazon.com",
        narration="Multi-item order",
        identity_algo_version=1,
        identity_method="exact",
        identity_fingerprint="fp_001",
        postings=(
            make_posting("imported", "Liabilities:CreditCard:Amex", -10500, rec_id="rec_parent", posting_index=0, stx_id="stx_split_001"),
            make_posting("contra", "Expenses:Books", 3500, rec_id="rec_line_1", posting_index=1, stx_id="stx_split_001"),
            make_posting("contra", "Expenses:Electronics", 5000, rec_id="rec_line_2", posting_index=2, stx_id="stx_split_001"),
            make_posting("contra", "Expenses:Household", 2000, rec_id="rec_line_3", posting_index=3, stx_id="stx_split_001"),
        ),
    )
    approved_set = ApprovedSet(transactions=(tx,))
    validate_approved_set(approved_set)
    files = render_ledger(approved_set)
    assert "txns/2026.beancount" in files
    content = files["txns/2026.beancount"].decode("utf-8")
    assert "Liabilities:CreditCard:Amex  -105.00 USD" in content
    assert "Expenses:Books  35.00 USD" in content
    assert "Expenses:Electronics  50.00 USD" in content
    assert "Expenses:Household  20.00 USD" in content


def test_compile_multileg_rejects_zero_contra():
    tx = ApprovedTransaction(
        staged_transaction_id="stx_invalid_0",
        source_document_id="doc_1",
        source_record_id="rec_1",
        proposed_date="2026-09-29",
        payee="Amazon",
        narration="Only imported",
        identity_algo_version=1,
        identity_method="exact",
        identity_fingerprint="fp_002",
        postings=(
            make_posting("imported", "Liabilities:CreditCard", -1000, posting_index=0, stx_id="stx_invalid_0"),
        ),
    )
    with pytest.raises(CompileInputError, match="must have at least 2 postings"):
        validate_approved_set(ApprovedSet(transactions=(tx,)))


def test_compile_multileg_rejects_multiple_imported_legs():
    tx = ApprovedTransaction(
        staged_transaction_id="stx_invalid_2_imp",
        source_document_id="doc_1",
        source_record_id="rec_1",
        proposed_date="2026-09-29",
        payee="Amazon",
        narration="Two imported legs",
        identity_algo_version=1,
        identity_method="exact",
        identity_fingerprint="fp_003",
        postings=(
            make_posting("imported", "Liabilities:CreditCard", -5000, posting_index=0, stx_id="stx_invalid_2_imp"),
            make_posting("imported", "Assets:Bank:Checking", -5000, posting_index=1, stx_id="stx_invalid_2_imp"),
            make_posting("contra", "Expenses:Books", 10000, posting_index=2, stx_id="stx_invalid_2_imp"),
        ),
    )
    with pytest.raises(CompileInputError, match="exactly one 'imported'"):
        validate_approved_set(ApprovedSet(transactions=(tx,)))


def test_compile_multileg_rejects_unknown_role():
    tx = ApprovedTransaction(
        staged_transaction_id="stx_invalid_role",
        source_document_id="doc_1",
        source_record_id="rec_1",
        proposed_date="2026-09-29",
        payee="Amazon",
        narration="Unknown role",
        identity_algo_version=1,
        identity_method="exact",
        identity_fingerprint="fp_004",
        postings=(
            make_posting("imported", "Liabilities:CreditCard", -5000, posting_index=0, stx_id="stx_invalid_role"),
            make_posting("third_party", "Expenses:Books", 5000, posting_index=1, stx_id="stx_invalid_role"),
        ),
    )
    with pytest.raises(CompileInputError, match="unknown roles"):
        validate_approved_set(ApprovedSet(transactions=(tx,)))


def test_compile_multileg_rejects_null_contra_account():
    tx = ApprovedTransaction(
        staged_transaction_id="stx_null_acct",
        source_document_id="doc_1",
        source_record_id="rec_1",
        proposed_date="2026-09-29",
        payee="Amazon",
        narration="Null account",
        identity_algo_version=1,
        identity_method="exact",
        identity_fingerprint="fp_005",
        postings=(
            make_posting("imported", "Liabilities:CreditCard", -5000, posting_index=0, stx_id="stx_null_acct"),
            make_posting("contra", None, 5000, posting_index=1, stx_id="stx_null_acct"),
        ),
    )
    with pytest.raises(CompileInputError, match="has NULL account"):
        validate_approved_set(ApprovedSet(transactions=(tx,)))


def test_compile_multileg_rejects_unbalanced():
    tx = ApprovedTransaction(
        staged_transaction_id="stx_unbalanced",
        source_document_id="doc_1",
        source_record_id="rec_1",
        proposed_date="2026-09-29",
        payee="Amazon",
        narration="Unbalanced",
        identity_algo_version=1,
        identity_method="exact",
        identity_fingerprint="fp_006",
        postings=(
            make_posting("imported", "Liabilities:CreditCard", -5000, posting_index=0, stx_id="stx_unbalanced"),
            make_posting("contra", "Expenses:Books", 3000, posting_index=1, stx_id="stx_unbalanced"),
            make_posting("contra", "Expenses:Tools", 1500, posting_index=2, stx_id="stx_unbalanced"),  # Sum is 4500 != 5000
        ),
    )
    with pytest.raises(CompileInputError, match="does not balance"):
        validate_approved_set(ApprovedSet(transactions=(tx,)))
