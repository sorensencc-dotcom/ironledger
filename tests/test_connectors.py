"""Comprehensive test suite for Phase 9 financial data connectors, rate limiters, and circuit breakers."""

from __future__ import annotations

import json
import sqlite3
import pytest

from ironledger.connectors.circuit_breaker import CircuitBreaker
from ironledger.connectors.models import (
    CircuitBreakerOpenError,
    CircuitState,
    ConnectorProvider,
    ConnectorRecord,
    PayloadParseError,
    ProtocolType,
    RateLimitExceededError,
    SyncStatus,
)
from ironledger.connectors.ofx import OFXConnector
from ironledger.connectors.plaid import PlaidConnector
from ironledger.connectors.rate_limiter import TokenBucketRateLimiter
from ironledger.connectors.registry import ConnectorRegistry
from ironledger.connectors.simplefin import SimpleFinConnector
from ironledger.db.migrations import migrate_governed


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    migrate_governed(conn)
    # Insert default ledger for tenant isolation testing
    conn.execute(
        """
        INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency, created_at, root_account, storage_root, is_active)
        VALUES ('ledger_main', 'Main Ledger', 'USD', datetime('now'), 'Assets', 'main', 1)
        """
    )
    conn.commit()
    return conn


# ============================================================================
# 1. Rate Limiter Tests
# ============================================================================


def test_rate_limiter_burst_and_consumption():
    limiter = TokenBucketRateLimiter(rate_limit_rpm=60, burst_capacity=5, initial_time_ms=0)
    assert limiter.get_available_tokens(now_ms=0) == 5

    # Consume 3 tokens
    assert limiter.acquire(3, now_ms=0) is True
    assert limiter.get_available_tokens(now_ms=0) == 2

    # Consume remaining 2 tokens
    assert limiter.acquire(2, now_ms=0) is True
    assert limiter.get_available_tokens(now_ms=0) == 0

    # Next acquire fails
    assert limiter.acquire(1, now_ms=0) is False
    # Wait time for 1 token at 60 rpm is 1000ms
    assert limiter.get_wait_time_ms(1, now_ms=0) == 1000


def test_rate_limiter_refill_math():
    limiter = TokenBucketRateLimiter(rate_limit_rpm=60, burst_capacity=10, initial_time_ms=0)
    assert limiter.acquire(10, now_ms=0) is True
    assert limiter.get_available_tokens(now_ms=0) == 0

    # Advance 5000ms -> should refill (5000 * 60) // 60000 = 5 tokens
    assert limiter.get_available_tokens(now_ms=5000) == 5
    assert limiter.acquire(4, now_ms=5000) is True
    assert limiter.get_available_tokens(now_ms=5000) == 1

    # Advance 100,000ms -> capped at burst_capacity (10)
    assert limiter.get_available_tokens(now_ms=105000) == 10


# ============================================================================
# 2. Circuit Breaker Tests
# ============================================================================


def test_circuit_breaker_transitions():
    breaker = CircuitBreaker(failure_threshold=3, base_cooldown_ms=1000, max_cooldown_ms=8000)
    assert breaker.state == CircuitState.CLOSED

    # Fail 1 & 2
    breaker.record_failure(now_ms=100)
    assert breaker.state == CircuitState.CLOSED
    breaker.record_failure(now_ms=200)
    assert breaker.state == CircuitState.CLOSED

    # Fail 3 -> Trips to OPEN
    breaker.record_failure(now_ms=300)
    assert breaker.state == CircuitState.OPEN
    assert breaker.consecutive_failures == 3

    # Fast-fail while cooldown is active
    assert breaker.allow_request(now_ms=500) is False
    with pytest.raises(CircuitBreakerOpenError):
        breaker.execute(lambda: "ok", now_ms=500)

    # Advance past cooldown (300 + 1000 = 1300) -> Transitions to HALF_OPEN on request
    assert breaker.allow_request(now_ms=1400) is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Trial probe succeeds -> Resets to CLOSED
    breaker.record_success(now_ms=1450)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


def test_circuit_breaker_half_open_failure_exponential_backoff():
    breaker = CircuitBreaker(failure_threshold=2, base_cooldown_ms=1000, max_cooldown_ms=4000)

    # Trip to OPEN
    breaker.record_failure(now_ms=100)
    breaker.record_failure(now_ms=200)
    assert breaker.state == CircuitState.OPEN

    # Transition to HALF_OPEN after 1000ms cooldown
    assert breaker.allow_request(now_ms=1300) is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Trial probe fails -> returns to OPEN with doubled cooldown (2000ms)
    breaker.record_failure(now_ms=1350)
    assert breaker.state == CircuitState.OPEN
    assert breaker.current_cooldown_ms == 2000

    # Check that 1500ms after failure is still OPEN
    assert breaker.allow_request(now_ms=2500) is False
    # 2100ms after failure (1350 + 2000 = 3350) allows next trial probe
    assert breaker.allow_request(now_ms=3400) is True
    assert breaker.state == CircuitState.HALF_OPEN


# ============================================================================
# 3. Protocol Parser Tests
# ============================================================================


def test_plaid_parser_success():
    provider = ConnectorProvider(
        provider_id="prov_plaid",
        name="Plaid Test",
        protocol_type=ProtocolType.PLAID,
        base_url="https://api.plaid.com",
    )
    connector = PlaidConnector(provider=provider)

    raw_payload = {
        "transactions": [
            {
                "transaction_id": "tx_plaid_001",
                "account_id": "acc_001",
                "date": "2026-09-01",
                "amount": 42.50,
                "iso_currency_code": "USD",
                "name": "Acme Coffee",
                "payment_channel": "in store",
            },
            {
                "transaction_id": "tx_plaid_002",
                "account_id": "acc_001",
                "date": "2026-09-02",
                "amount": -1500.00,
                "iso_currency_code": "USD",
                "merchant_name": "Direct Deposit Employer",
            },
        ]
    }

    records = connector.parse_payload(raw_payload)
    assert len(records) == 2
    assert records[0].record_id == "tx_plaid_001"
    assert records[0].amount_minor == 4250
    assert records[0].payee == "Acme Coffee"
    assert records[0].posted_date == "2026-09-01"

    assert records[1].record_id == "tx_plaid_002"
    assert records[1].amount_minor == -150000
    assert records[1].payee == "Direct Deposit Employer"


def test_simplefin_parser_success():
    provider = ConnectorProvider(
        provider_id="prov_simplefin",
        name="SimpleFIN Test",
        protocol_type=ProtocolType.SIMPLEFIN,
        base_url="https://bridge.simplefin.org",
    )
    connector = SimpleFinConnector(provider=provider)

    raw_payload = {
        "accounts": [
            {
                "id": "sfin_acc_100",
                "currency": "USD",
                "transactions": [
                    {
                        "id": "sfin_tx_01",
                        "posted": 1788220800,  # 2026-09-01
                        "amount": "-23.75",
                        "payee": "Grocery Market",
                        "memo": "Debit card",
                    }
                ],
            }
        ]
    }

    records = connector.parse_payload(raw_payload)
    assert len(records) == 1
    assert records[0].record_id == "sfin_tx_01"
    assert records[0].account_id == "sfin_acc_100"
    assert records[0].amount_minor == -2375
    assert records[0].payee == "Grocery Market"
    assert records[0].posted_date == "2026-09-01"


def test_ofx_parser_success():
    provider = ConnectorProvider(
        provider_id="prov_ofx",
        name="OFX Test",
        protocol_type=ProtocolType.OFX,
        base_url="https://ofx.bank.com",
    )
    connector = OFXConnector(provider=provider)

    raw_ofx = """
    <OFX>
      <BANKTRANLIST>
        <STMTTRN>
          <TRNTYPE>DEBIT
          <DTPOSTED>20260905120000
          <TRNAMT>-89.95
          <FITID>OFX-TX-9988
          <NAME>Hardware Store
          <MEMO>Tools and supplies
        </STMTTRN>
      </BANKTRANLIST>
    </OFX>
    """

    records = connector.parse_payload(raw_ofx)
    assert len(records) == 1
    assert records[0].record_id == "OFX-TX-9988"
    assert records[0].amount_minor == -8995
    assert records[0].posted_date == "2026-09-05"
    assert records[0].payee == "Hardware Store"
    assert records[0].memo == "Tools and supplies"


def test_parser_malformed_payload_rejection():
    provider = ConnectorProvider(
        provider_id="prov_plaid",
        name="Plaid Test",
        protocol_type=ProtocolType.PLAID,
        base_url="https://api.plaid.com",
    )
    connector = PlaidConnector(provider=provider)

    with pytest.raises(PayloadParseError):
        connector.parse_payload({"invalid_key": []})

    with pytest.raises(PayloadParseError):
        connector.parse_payload("not valid json string {")


# ============================================================================
# 4. Registry and End-to-End Governed Sync Tests
# ============================================================================


def test_connector_registry_and_governed_sync(db_conn: sqlite3.Connection):
    registry = ConnectorRegistry()
    provider = ConnectorProvider(
        provider_id="prov_live_plaid",
        name="Live Plaid Banking",
        protocol_type=ProtocolType.PLAID,
        base_url="https://sandbox.plaid.com",
        rate_limit_rpm=120,
        burst_capacity=5,
    )

    registry.save_provider(db_conn, provider)
    retrieved = registry.get_provider(db_conn, "prov_live_plaid")
    assert retrieved is not None
    assert retrieved.name == "Live Plaid Banking"
    assert retrieved.rate_limit_rpm == 120

    # Mock response payload
    mock_payload = {
        "transactions": [
            {
                "transaction_id": "plaid_live_01",
                "account_id": "checking_01",
                "date": "2026-09-10",
                "amount": 105.00,
                "name": "Restaurant Dinner",
            }
        ]
    }

    # Execute Sync
    sync_result = registry.sync_provider(
        conn=db_conn,
        ledger_id="ledger_main",
        provider_id="prov_live_plaid",
        credentials={"mock_response": mock_payload},
        start_date="2026-09-01",
        end_date="2026-09-10",
    )

    assert sync_result.status == SyncStatus.SUCCESS
    assert sync_result.records_fetched == 1
    assert sync_result.records_staged == 1

    # Verify database persistence in connector_sync_runs
    cur = db_conn.execute("SELECT status, records_fetched, records_staged FROM connector_sync_runs WHERE run_id = ?", (sync_result.run_id,))
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "SUCCESS"
    assert row[1] == 1
    assert row[2] == 1

    # Verify staged transaction in tenant_staging_operations
    cur = db_conn.execute("SELECT operation_json FROM tenant_staging_operations WHERE ledger_id = 'ledger_main'")
    staged = cur.fetchall()
    assert len(staged) == 1
    op_data = json.loads(staged[0][0])
    assert op_data["record_id"] == "plaid_live_01"
    assert op_data["amount_minor"] == 10500