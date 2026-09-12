"""Outbox dispatcher, webhook dispatcher, and peer event ingestion registry with lease fencing."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Final

from ironledger.events.envelope import (
    FederatedEvent,
    canonical_event_bytes,
    validate_federated_event,
)
from ironledger.events.models import DeliveryResult, WebhookDelivery
from ironledger.events.signer import WebhookSigner
from ironledger.security.envelope import EnvelopeCiphertext, EnvelopeEncryptor
from ironledger.security.key_provider import EnvironmentKeyProvider, KeyProvider


DEFAULT_LEASE_SECONDS: Final[int] = 30


class OutboxDispatchError(ValueError):
    """Raised when outbox dispatch or lease acquisition fails."""


class OutboxDispatcher:
    """Manages fenced outbox leasing and peer event synchronization."""

    @staticmethod
    def claim_batch(
        conn: sqlite3.Connection,
        worker_id: str,
        batch_size: int = 50,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> tuple[str, list[FederatedEvent]]:
        """Claim an unpublished batch of events using randomized lease fencing tokens."""
        now = datetime.now(timezone.utc)
        now_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        lease_expires = (now + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fence_token = uuid.uuid4().hex

        cursor = conn.cursor()

        # Find candidate events (unpublished and unleased or lease expired)
        cursor.execute(
            """
            SELECT event_id, seq, tenant_id, ledger_id, event_type, source, severity,
                   payload_json, metadata_json, created_at_utc
            FROM federated_event_outbox
            WHERE published_to_peers = 0
              AND (lease_expires_at_utc IS NULL OR lease_expires_at_utc < ?)
            ORDER BY seq ASC
            LIMIT ?
            """,
            (now_utc, batch_size),
        )
        rows = cursor.fetchall()
        if not rows:
            return fence_token, []

        event_ids = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in event_ids)

        # Atomic lease acquisition
        cursor.execute(
            f"""
            UPDATE federated_event_outbox
            SET lease_owner_id = ?,
                lease_fence_token = ?,
                lease_expires_at_utc = ?
            WHERE event_id IN ({placeholders})
              AND published_to_peers = 0
              AND (lease_expires_at_utc IS NULL OR lease_expires_at_utc < ?)
            """,
            [worker_id, fence_token, lease_expires] + event_ids + [now_utc],
        )

        claimed_events: list[FederatedEvent] = []
        for r in rows:
            claimed_events.append(
                FederatedEvent(
                    event_id=r[0],
                    tenant_id=r[2],
                    ledger_id=r[3],
                    event_type=r[4],
                    source=r[5],
                    severity=r[6],
                    payload=json.loads(r[7]),
                    metadata=json.loads(r[8]),
                    occurred_at=r[9],
                    recorded_at=r[9],
                )
            )

        return fence_token, claimed_events

    @staticmethod
    def acknowledge_batch(
        conn: sqlite3.Connection,
        event_ids: list[str],
        fence_token: str,
    ) -> int:
        """Mark a claimed batch as published if the fencing token is still valid."""
        if not event_ids:
            return 0

        placeholders = ",".join("?" for _ in event_ids)
        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE federated_event_outbox
            SET published_to_peers = 1,
                lease_owner_id = NULL,
                lease_fence_token = NULL,
                lease_expires_at_utc = NULL
            WHERE event_id IN ({placeholders})
              AND lease_fence_token = ?
            """,
            event_ids + [fence_token],
        )
        return cursor.rowcount

    @staticmethod
    def ingest_peer_event(
        conn: sqlite3.Connection,
        cluster_id: str,
        event: FederatedEvent,
    ) -> bool:
        """Idempotently ingest a federated event from a peer cluster."""
        validate_federated_event(event)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = conn.cursor()

        # Check if already ingested from this cluster
        cursor.execute(
            """
            SELECT 1 FROM peer_ingested_events WHERE cluster_id = ? AND event_id = ?
            """,
            (cluster_id, event.event_id),
        )
        if cursor.fetchone():
            return False

        # Record peer ingestion
        cursor.execute(
            """
            INSERT INTO peer_ingested_events (cluster_id, event_id, ingested_at_utc)
            VALUES (?, ?, ?)
            """,
            (cluster_id, event.event_id, now_utc),
        )

        # Persist into local governance audit trail
        import hashlib
        canonical_bytes = canonical_event_bytes(event)
        envelope_hash = hashlib.sha256(canonical_bytes).hexdigest()

        cursor.execute(
            """
            INSERT INTO governance_audit_events (
                ledger_id, actor, action, target, before_state_json, after_state_json,
                envelope_hash, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.ledger_id,
                f"peer:{cluster_id}",
                event.event_type,
                f"event:{event.event_id}",
                "{}",
                json.dumps(event.payload, sort_keys=True),
                envelope_hash,
                event.recorded_at,
            ),
        )

        return True


class WebhookDispatcher:
    """Claims leased deliveries, executes signed HTTP POST webhooks, and manages retry / DLQ lifecycle."""

    @classmethod
    def claim_deliveries(
        cls,
        conn: sqlite3.Connection,
        worker_id: str,
        batch_size: int = 10,
        lease_seconds: int = 60,
        ledger_id: str | None = None,
    ) -> list[WebhookDelivery]:
        now = datetime.now(timezone.utc)
        now_iso = now.strftime("%Y-%m-%d %H:%M:%S.%fZ")
        lease_until = (now + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S.%fZ")

        cursor = conn.cursor()
        if ledger_id:
            cursor.execute(
                """
                SELECT ledger_id, delivery_id, event_id, subscription_id, retry_count, next_retry_at_utc, created_at_utc
                FROM webhook_deliveries
                WHERE ledger_id = ? AND status = 'PENDING' AND next_retry_at_utc <= ?
                ORDER BY next_retry_at_utc ASC
                LIMIT ?;
                """,
                (ledger_id, now_iso, batch_size),
            )
        else:
            cursor.execute(
                """
                SELECT ledger_id, delivery_id, event_id, subscription_id, retry_count, next_retry_at_utc, created_at_utc
                FROM webhook_deliveries
                WHERE status = 'PENDING' AND next_retry_at_utc <= ?
                ORDER BY next_retry_at_utc ASC
                LIMIT ?;
                """,
                (now_iso, batch_size),
            )

        rows = cursor.fetchall()
        if not rows:
            return []

        claimed: list[WebhookDelivery] = []
        for row in rows:
            l_id, d_id, e_id, s_id, r_count, next_retry, c_at = row
            cursor.execute(
                """
                UPDATE webhook_deliveries
                SET status = 'PROCESSING',
                    leased_by = ?,
                    leased_until_utc = ?
                WHERE ledger_id = ? AND delivery_id = ? AND status = 'PENDING';
                """,
                (worker_id, lease_until, l_id, d_id),
            )
            if cursor.rowcount > 0:
                claimed.append(
                    WebhookDelivery(
                        ledger_id=l_id,
                        delivery_id=d_id,
                        event_id=e_id,
                        subscription_id=s_id,
                        status="PROCESSING",
                        retry_count=r_count,
                        next_retry_at_utc=next_retry,
                        leased_by=worker_id,
                        leased_until_utc=lease_until,
                        created_at_utc=c_at,
                    )
                )

        conn.commit()
        return claimed

    @classmethod
    def dispatch_delivery(
        cls,
        conn: sqlite3.Connection,
        delivery: WebhookDelivery,
        key_provider: KeyProvider | None = None,
        http_client: Callable[[str, dict[str, str], bytes], tuple[int, str]] | None = None,
        max_retries: int = 5,
    ) -> DeliveryResult:
        if key_provider is None:
            key_provider = EnvironmentKeyProvider()

        cursor = conn.cursor()
        # 1. Fetch event payload
        cursor.execute(
            """
            SELECT payload_json FROM event_outbox
            WHERE ledger_id = ? AND event_id = ?;
            """,
            (delivery.ledger_id, delivery.event_id),
        )
        row = cursor.fetchone()
        if not row:
            cls._mark_dead_letter(conn, delivery, None, "Event not found in outbox", delivery.retry_count + 1)
            return DeliveryResult(success=False, error="Event not found in outbox", should_retry=False)
        payload_json = row[0]

        # 2. Fetch subscription details and decrypt secret
        cursor.execute(
            """
            SELECT target_url, kek_key_id, encrypted_dek_blob, dek_iv_hex, dek_auth_tag_hex,
                   encrypted_secret_blob, secret_iv_hex, secret_auth_tag_hex, is_active
            FROM webhook_subscriptions
            WHERE ledger_id = ? AND subscription_id = ?;
            """,
            (delivery.ledger_id, delivery.subscription_id),
        )
        sub_row = cursor.fetchone()
        if not sub_row:
            cls._mark_dead_letter(conn, delivery, None, "Subscription not found", delivery.retry_count + 1)
            return DeliveryResult(success=False, error="Subscription not found", should_retry=False)

        target_url, kek_id, dek_blob, dek_iv, dek_tag, sec_blob, sec_iv, sec_tag, is_active = sub_row
        if not is_active:
            cls._mark_dead_letter(conn, delivery, None, "Subscription inactive", delivery.retry_count + 1)
            return DeliveryResult(success=False, error="Subscription inactive", should_retry=False)

        try:
            envelope = EnvelopeCiphertext(
                kek_key_id=kek_id,
                encrypted_dek_blob=dek_blob,
                dek_iv_hex=dek_iv,
                dek_auth_tag_hex=dek_tag,
                encrypted_payload_blob=sec_blob,
                payload_iv_hex=sec_iv,
                payload_auth_tag_hex=sec_tag,
            )
            aad = f"{delivery.ledger_id}:webhook:{delivery.subscription_id}".encode("utf-8")
            secret_bytes = EnvelopeEncryptor.decrypt(envelope, key_provider, aad)
            secret = secret_bytes.decode("utf-8")
        except Exception as e:
            cls._mark_dead_letter(conn, delivery, None, f"Envelope decryption failed: {e}", delivery.retry_count + 1)
            return DeliveryResult(success=False, error=f"Decryption failed: {e}", should_retry=False)

        # 3. Sign and execute request
        timestamp = int(datetime.now(timezone.utc).timestamp())
        headers = WebhookSigner.build_headers(
            secret=secret,
            timestamp=timestamp,
            event_id=delivery.event_id,
            delivery_id=delivery.delivery_id,
            payload_json=payload_json,
        )

        status_code: int | None = None
        error_msg: str | None = None
        success = False

        if http_client is not None:
            try:
                status_code, error_msg = http_client(target_url, headers, payload_json.encode("utf-8"))
                if 200 <= status_code < 300:
                    success = True
            except Exception as exc:
                error_msg = str(exc)
        else:
            try:
                req = urllib.request.Request(
                    target_url,
                    data=payload_json.encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status_code = resp.getcode()
                    if 200 <= status_code < 300:
                        success = True
            except urllib.error.HTTPError as he:
                status_code = he.code
                error_msg = f"HTTP error {he.code}: {he.reason}"
            except Exception as exc:
                error_msg = f"Network failure: {exc}"

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")

        if success:
            cursor.execute(
                """
                UPDATE webhook_deliveries
                SET status = 'DELIVERED',
                    last_status_code = ?,
                    last_error = NULL,
                    leased_by = NULL,
                    leased_until_utc = NULL,
                    completed_at_utc = ?
                WHERE ledger_id = ? AND delivery_id = ?;
                """,
                (status_code, now_iso, delivery.ledger_id, delivery.delivery_id),
            )
            conn.commit()
            return DeliveryResult(success=True, status_code=status_code)
        else:
            attempt = delivery.retry_count + 1
            if attempt >= max_retries:
                cls._mark_dead_letter(conn, delivery, status_code, error_msg or "Max retries exceeded", attempt)
                return DeliveryResult(success=False, status_code=status_code, error=error_msg, should_retry=False)
            else:
                # Integer exponential backoff: min(3600, 2 ** attempt * 10)
                backoff_seconds = min(3600, (2 ** attempt) * 10)
                next_retry = (datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)).strftime("%Y-%m-%d %H:%M:%S.%fZ")
                cursor.execute(
                    """
                    UPDATE webhook_deliveries
                    SET status = 'PENDING',
                        retry_count = ?,
                        next_retry_at_utc = ?,
                        last_status_code = ?,
                        last_error = ?,
                        leased_by = NULL,
                        leased_until_utc = NULL
                    WHERE ledger_id = ? AND delivery_id = ?;
                    """,
                    (attempt, next_retry, status_code, error_msg, delivery.ledger_id, delivery.delivery_id),
                )
                conn.commit()
                return DeliveryResult(success=False, status_code=status_code, error=error_msg, should_retry=True)

    @classmethod
    def _mark_dead_letter(
        cls,
        conn: sqlite3.Connection,
        delivery: WebhookDelivery,
        status_code: int | None,
        error_msg: str,
        attempt_count: int,
    ) -> None:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")
        dlq_id = f"dlq_{uuid.uuid4().hex[:16]}"
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE webhook_deliveries
            SET status = 'DEAD_LETTERED',
                last_status_code = ?,
                last_error = ?,
                leased_by = NULL,
                leased_until_utc = NULL,
                completed_at_utc = ?
            WHERE ledger_id = ? AND delivery_id = ?;
            """,
            (status_code, error_msg, now_iso, delivery.ledger_id, delivery.delivery_id),
        )
        cursor.execute(
            """
            INSERT INTO webhook_delivery_dlq (
                ledger_id, dlq_entry_id, delivery_id, event_id, subscription_id,
                status_code, last_error, attempt_count, failed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                delivery.ledger_id,
                dlq_id,
                delivery.delivery_id,
                delivery.event_id,
                delivery.subscription_id,
                status_code,
                error_msg,
                attempt_count,
                now_iso,
            ),
        )
        conn.commit()

