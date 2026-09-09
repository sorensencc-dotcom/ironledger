import pytest
from pydantic import ValidationError

from ironledger.web.schemas import (
    PostingSchema,
    StagedTransactionResponse,
    RuleDriftResponse,
    CompileRequest,
    BalanceItemResponse,
    FreshnessResponse,
    SafeModeStatusResponse,
)


def test_posting_schema_valid():
    p = PostingSchema(
        account="Assets:Checking:Primary",
        currency="USD",
        minor_units=1050,
        scale=2,
    )
    assert p.account == "Assets:Checking:Primary"
    assert p.currency == "USD"
    assert p.minor_units == 1050
    assert p.scale == 2


def test_posting_schema_rejects_float_and_bool():
    with pytest.raises(ValidationError):
        PostingSchema(
            account="Assets:Checking:Primary",
            currency="USD",
            minor_units=10.50,  # float rejected
            scale=2,
        )

    with pytest.raises(ValidationError):
        PostingSchema(
            account="Assets:Checking:Primary",
            currency="USD",
            minor_units=True,  # bool rejected
            scale=2,
        )


def test_posting_schema_invalid_scale_mismatch():
    with pytest.raises(ValidationError):
        PostingSchema(
            account="Assets:Checking:Primary",
            currency="USD",
            minor_units=1050,
            scale=3,  # USD scale is 2
        )


def test_posting_schema_invalid_currency():
    with pytest.raises(ValidationError):
        PostingSchema(
            account="Assets:Checking:Primary",
            currency="INVALID",
            minor_units=1050,
            scale=2,
        )


def test_posting_schema_invalid_account():
    with pytest.raises(ValidationError):
        PostingSchema(
            account="invalid_account",
            currency="USD",
            minor_units=1050,
            scale=2,
        )


def test_staged_transaction_response_valid():
    txn = StagedTransactionResponse(
        staged_id="stg_01abc",
        source_document_id="doc_01abc",
        source_record_id="rec_01abc",
        date="2026-09-01",
        payee="Acme Corp",
        narration="Office supplies",
        currency="USD",
        minor_units=-4500,
        scale=2,
        postings=[
            PostingSchema(
                account="Expenses:Office:Supplies",
                currency="USD",
                minor_units=4500,
                scale=2,
            ),
            PostingSchema(
                account="Assets:Checking:Primary",
                currency="USD",
                minor_units=-4500,
                scale=2,
            ),
        ],
        status="pending",
        confidence_score=0.95,
        matched_rule_id="rule_123",
        notes="Automated rule match",
    )
    assert txn.staged_id == "stg_01abc"
    assert txn.minor_units == -4500
    assert len(txn.postings) == 2


def test_staged_transaction_response_rejects_float_amount():
    with pytest.raises(ValidationError):
        StagedTransactionResponse(
            staged_id="stg_01abc",
            source_document_id="doc_01abc",
            source_record_id="rec_01abc",
            date="2026-09-01",
            payee="Acme Corp",
            narration="Office supplies",
            currency="USD",
            minor_units=-45.00,  # float rejected
            scale=2,
            postings=[],
            status="pending",
        )


def test_rule_drift_response():
    drift = RuleDriftResponse(
        rule_id="rule_123",
        rule_name="Starbucks Expense Rule",
        total_hits=50,
        recent_hits=10,
        override_count=2,
        override_rate=0.20,
        confidence_trend=-0.15,
        drift_status="warning",
    )
    assert drift.rule_id == "rule_123"
    assert drift.drift_status == "warning"


def test_compile_request():
    req = CompileRequest(
        dry_run=True,
        rebuild_projection=True,
        safe_mode_token="tok_123456",
    )
    assert req.dry_run is True
    assert req.rebuild_projection is True
    assert req.safe_mode_token == "tok_123456"
