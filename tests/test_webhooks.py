"""Comprehensive test suite for Webhook Dispatcher and Event Notification Fabric."""

from __future__ import annotations

import os
import sqlite3
import time
import pytest
from datetime import datetime, timezone, timedelta

from ironledger.db.migrations import migrate_governed
from ironledger.events import (
    DeliveryResult,
    EventOutboxPublisher,
    OutboxEvent,
    WebhookDelivery,
    WebhookDispatcher,
    WebhookSigner,
    WebhookSubscription,
    reconcile_abandoned_deliveries,
)
from ironledger.security.key_provider import EnvironmentKeyProvider


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    # Ensure test environment key is set (32 bytes in hex or base64)
    monkeypatch.setenv("IRONLEDGER_KEK_TEST_V1", "0123456789012345678901234567890101234567890123456789012345678901")
    monkeypatch.setenv("IRONLEDGER_KEK_DEFAULT", "0123456789012345678901234567890101234567890123456789012345678901")

    db_file = str(tmp_path / "test_webhooks.db")
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    # Seed a test ledger
    conn.execute(
        """
        INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency, created_at, root_account, storage_root, is_active)
        VALUES ('led_test1', 'Test Ledger', 'USD', datetime('now'), 'Assets', 't1', 1);
        """
    )
    conn.commit()

    yield conn
    conn.close()


def test_webhook_signer_generation_and_verification():
    secret = "whsec_test_secret_key_12345"
    timestamp = int(time.time())
    event_id = "evt_001"
    delivery_id = "del_001"
    payload_json = '{"amount":1000,"currency":"USD"}'

    headers = WebhookSigner.build_headers(secret, timestamp, event_id, delivery_id, payload_json)
    assert headers["X-IronLedger-Timestamp"] == str(timestamp)
    assert headers["X-IronLedger-Event-Id"] == event_id
    assert headers["X-IronLedger-Delivery-Id"] == delivery_id
    assert "v1=" in headers["X-IronLedger-Signature"]

    # Verify signature passes
    assert WebhookSigner.verify_signature(secret, headers["X-IronLedger-Signature"], payload_json, current_time=timestamp)

    # Tampered payload fails
    tampered_payload = '{"amount":9999,"currency":"USD"}'
    assert not WebhookSigner.verify_signature(secret, headers["X-IronLedger-Signature"], tampered_payload, current_time=timestamp)

    # Expired timestamp fails
    future_time = timestamp + 301
    assert not WebhookSigner.verify_signature(secret, headers["X-IronLedger-Signature"], payload_json, tolerance_seconds=300, current_time=future_time)

    # Wrong secret fails
    assert not WebhookSigner.verify_signature("wrong_secret", headers["X-IronLedger-Signature"], payload_json, current_time=timestamp)


def test_event_outbox_immutability_triggers(test_db):
    conn = test_db
    event = EventOutboxPublisher.publish_event(
        conn=conn,
        ledger_id="led_test1",
        event_type="TRANSACTION_POSTED",
        payload={"transaction_id": "tx_1", "amount": 500},
    )

    # Assert UPDATE is aborted by trigger
    with pytest.raises(sqlite3.IntegrityError, match="event_outbox is append-only"):
        conn.execute(
            "UPDATE event_outbox SET event_type = 'MUTATED' WHERE ledger_id = ? AND event_id = ?;",
            (event.ledger_id, event.event_id),
        )

    # Assert DELETE is aborted by trigger
    with pytest.raises(sqlite3.IntegrityError, match="event_outbox is append-only"):
        conn.execute(
            "DELETE FROM event_outbox WHERE ledger_id = ? AND event_id = ?;",
            (event.ledger_id, event.event_id),
        )


def test_subscription_registration_and_event_fanout(test_db):
    conn = test_db
    key_provider = EnvironmentKeyProvider()

    # Register subscription for TRANSACTION_POSTED
    sub1 = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_test1",
        target_url="https://api.example.com/webhooks/tx",
        secret="whsec_secret_tx_123",
        event_types=["TRANSACTION_POSTED"],
        key_provider=key_provider,
        kek_key_id="test_v1",
    )

    # Register wildcard subscription
    sub2 = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_test1",
        target_url="https://api.example.com/webhooks/all",
        secret="whsec_secret_all_456",
        event_types=["*"],
        key_provider=key_provider,
        kek_key_id="test_v1",
    )

    # Register unrelated subscription
    sub3 = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_test1",
        target_url="https://api.example.com/webhooks/sync",
        secret="whsec_secret_sync_789",
        event_types=["SYNC_COMPLETED"],
        key_provider=key_provider,
        kek_key_id="test_v1",
    )

    # Publish TRANSACTION_POSTED event
    event = EventOutboxPublisher.publish_event(
        conn=conn,
        ledger_id="led_test1",
        event_type="TRANSACTION_POSTED",
        payload={"tx": 100},
    )

    # Check deliveries created
    cursor = conn.cursor()
    cursor.execute(
        "SELECT subscription_id, status FROM webhook_deliveries WHERE ledger_id = ? AND event_id = ?;",
        (event.ledger_id, event.event_id),
    )
    deliveries = cursor.fetchall()
    assert len(deliveries) == 2
    sub_ids = {d[0] for d in deliveries}
    assert sub1.subscription_id in sub_ids
    assert sub2.subscription_id in sub_ids
    assert sub3.subscription_id not in sub_ids


def test_webhook_dispatcher_claim_and_deliver_success(test_db):
    conn = test_db
    key_provider = EnvironmentKeyProvider()

    sub = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_test1",
        target_url="https://api.example.com/webhook",
        secret="secret_abc_123",
        event_types=["*"],
        key_provider=key_provider,
        kek_key_id="test_v1",
    )

    event = EventOutboxPublisher.publish_event(
        conn=conn,
        ledger_id="led_test1",
        event_type="TEST_EVENT",
        payload={"msg": "hello"},
    )

    # Claim delivery
    claimed = WebhookDispatcher.claim_deliveries(conn, worker_id="worker_node_1", batch_size=5)
    assert len(claimed) == 1
    delivery = claimed[0]
    assert delivery.status == "PROCESSING"
    assert delivery.leased_by == "worker_node_1"

    # Mock HTTP client
    called_requests = []

    def mock_http(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        called_requests.append((url, headers, body))
        return 200, "OK"

    result = WebhookDispatcher.dispatch_delivery(
        conn=conn,
        delivery=delivery,
        key_provider=key_provider,
        http_client=mock_http,
    )

    assert result.success is True
    assert result.status_code == 200
    assert len(called_requests) == 1
    assert called_requests[0][0] == "https://api.example.com/webhook"
    assert "v1=" in called_requests[0][1]["X-IronLedger-Signature"]

    # Verify database status is DELIVERED
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, last_status_code, completed_at_utc FROM webhook_deliveries WHERE delivery_id = ?;",
        (delivery.delivery_id,),
    )
    row = cursor.fetchone()
    assert row[0] == "DELIVERED"
    assert row[1] == 200
    assert row[2] is not None


def test_webhook_dispatcher_retry_and_dlq_lifecycle(test_db):
    conn = test_db
    key_provider = EnvironmentKeyProvider()

    sub = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_test1",
        target_url="https://api.example.com/failing",
        secret="secret_failing",
        event_types=["*"],
        key_provider=key_provider,
        kek_key_id="test_v1",
    )

    event = EventOutboxPublisher.publish_event(
        conn=conn,
        ledger_id="led_test1",
        event_type="FAIL_EVENT",
        payload={"msg": "fail"},
    )

    claimed = WebhookDispatcher.claim_deliveries(conn, worker_id="worker_1", batch_size=1)
    delivery = claimed[0]

    # Mock failing HTTP client (500 Internal Error)
    def mock_failing_http(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        return 500, "Internal Server Error"

    # Attempt 1: Retry scheduled
    result1 = WebhookDispatcher.dispatch_delivery(
        conn=conn,
        delivery=delivery,
        key_provider=key_provider,
        http_client=mock_failing_http,
        max_retries=3,
    )
    assert result1.success is False
    assert result1.should_retry is True

    cursor = conn.cursor()
    cursor.execute("SELECT status, retry_count, last_status_code FROM webhook_deliveries WHERE delivery_id = ?;", (delivery.delivery_id,))
    row1 = cursor.fetchone()
    assert row1[0] == "PENDING"
    assert row1[1] == 1
    assert row1[2] == 500

    # Simulate Attempt 2
    delivery.retry_count = 1
    result2 = WebhookDispatcher.dispatch_delivery(
        conn=conn,
        delivery=delivery,
        key_provider=key_provider,
        http_client=mock_failing_http,
        max_retries=3,
    )
    assert result2.should_retry is True

    # Attempt 3: Max retries (3) reached -> DLQ
    delivery.retry_count = 2
    result3 = WebhookDispatcher.dispatch_delivery(
        conn=conn,
        delivery=delivery,
        key_provider=key_provider,
        http_client=mock_failing_http,
        max_retries=3,
    )
    assert result3.success is False
    assert result3.should_retry is False

    # Verify DLQ
    cursor.execute("SELECT status FROM webhook_deliveries WHERE delivery_id = ?;", (delivery.delivery_id,))
    assert cursor.fetchone()[0] == "DEAD_LETTERED"

    cursor.execute(
        "SELECT ledger_id, delivery_id, status_code, attempt_count FROM webhook_delivery_dlq WHERE delivery_id = ?;",
        (delivery.delivery_id,),
    )
    dlq_row = cursor.fetchone()
    assert dlq_row is not None
    assert dlq_row[0] == "led_test1"
    assert dlq_row[1] == delivery.delivery_id
    assert dlq_row[2] == 500
    assert dlq_row[3] == 3


def test_lease_reconciliation_recovers_abandoned_deliveries(test_db):
    conn = test_db
    key_provider = EnvironmentKeyProvider()

    sub = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_test1",
        target_url="https://api.example.com/hook",
        secret="sec123",
        event_types=["*"],
        key_provider=key_provider,
        kek_key_id="test_v1",
    )

    event = EventOutboxPublisher.publish_event(
        conn=conn,
        ledger_id="led_test1",
        event_type="STUCK_EVENT",
        payload={"status": "stuck"},
    )

    # Claim delivery with lease 5 seconds
    claimed = WebhookDispatcher.claim_deliveries(conn, worker_id="crashed_worker", batch_size=1, lease_seconds=5)
    delivery = claimed[0]

    # Future time past expiration
    future_time = (datetime.now(timezone.utc) + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S.%fZ")

    # Run reconciliation
    reconciled = reconcile_abandoned_deliveries(conn, now_iso=future_time)
    assert reconciled == 1

    # Verify delivery is PENDING and lease cleared
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, leased_by, leased_until_utc FROM webhook_deliveries WHERE delivery_id = ?;",
        (delivery.delivery_id,),
    )
    row = cursor.fetchone()
    assert row[0] == "PENDING"
    assert row[1] is None
    assert row[2] is None


def test_webhook_cross_tenant_isolation(test_db):
    conn = test_db
    key_provider = EnvironmentKeyProvider()

    # Create second ledger
    conn.execute(
        """
        INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency, created_at, root_account, storage_root, is_active)
        VALUES ('led_test2', 'Test Ledger 2', 'EUR', datetime('now'), 'Assets', 't2', 1);
        """
    )
    conn.commit()

    # Create subscription in ledger 1
    sub1 = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_test1",
        target_url="https://api.example.com/hook1",
        secret="sec1",
        event_types=["*"],
        key_provider=key_provider,
        kek_key_id="test_v1",
    )

    # Publish event in ledger 2
    event2 = EventOutboxPublisher.publish_event(
        conn=conn,
        ledger_id="led_test2",
        event_type="TENANT2_EVENT",
        payload={"tenant": "2"},
    )

    # Deliveries in ledger 2 should NOT link to subscription in ledger 1
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM webhook_deliveries WHERE ledger_id = 'led_test2';")
    assert len(cursor.fetchall()) == 0

    # Cross-tenant delivery insert must fail composite foreign key check
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO webhook_deliveries (
                ledger_id, delivery_id, event_id, subscription_id,
                status, retry_count, next_retry_at_utc, created_at_utc
            ) VALUES ('led_test2', 'del_cross', ?, ?, 'PENDING', 0, datetime('now'), datetime('now'));
            """,
            (event2.event_id, sub1.subscription_id),
        )

