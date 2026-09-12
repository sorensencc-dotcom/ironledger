"""Transactional outbox publisher and webhook subscription manager."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ironledger.events.models import OutboxEvent, WebhookSubscription
from ironledger.security.envelope import EnvelopeCiphertext, EnvelopeEncryptor
from ironledger.security.key_provider import EnvironmentKeyProvider, KeyProvider


class EventOutboxPublisher:
    """Manages transactional event outbox publication and webhook delivery enqueueing."""

    @classmethod
    def register_subscription(
        cls,
        conn: sqlite3.Connection,
        ledger_id: str,
        target_url: str,
        secret: str,
        event_types: list[str],
        subscription_id: str | None = None,
        key_provider: KeyProvider | None = None,
        kek_key_id: str = "default",
    ) -> WebhookSubscription:
        if subscription_id is None:
            subscription_id = f"sub_{uuid.uuid4().hex[:16]}"
        if key_provider is None:
            key_provider = EnvironmentKeyProvider()

        # Generate envelope encryption for the webhook secret
        aad = f"{ledger_id}:webhook:{subscription_id}".encode("utf-8")
        encrypted = EnvelopeEncryptor.encrypt(
            payload=secret.encode("utf-8"),
            key_provider=key_provider,
            kek_key_id=kek_key_id,
            aad=aad,
        )
        secret_fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        event_types_json = json.dumps(event_types)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO webhook_subscriptions (
                ledger_id, subscription_id, target_url, kek_key_id,
                encrypted_dek_blob, dek_iv_hex, dek_auth_tag_hex,
                encrypted_secret_blob, secret_iv_hex, secret_auth_tag_hex,
                secret_fingerprint_hex, event_types_json, is_active, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?);
            """,
            (
                ledger_id,
                subscription_id,
                target_url,
                encrypted.kek_key_id,
                encrypted.encrypted_dek_blob,
                encrypted.dek_iv_hex,
                encrypted.dek_auth_tag_hex,
                encrypted.encrypted_payload_blob,
                encrypted.payload_iv_hex,
                encrypted.payload_auth_tag_hex,
                secret_fingerprint,
                event_types_json,
                now_iso,
            ),
        )
        conn.commit()

        return WebhookSubscription(
            ledger_id=ledger_id,
            subscription_id=subscription_id,
            target_url=target_url,
            kek_key_id=encrypted.kek_key_id,
            encrypted_dek_blob=encrypted.encrypted_dek_blob,
            dek_iv_hex=encrypted.dek_iv_hex,
            dek_auth_tag_hex=encrypted.dek_auth_tag_hex,
            encrypted_secret_blob=encrypted.encrypted_payload_blob,
            secret_iv_hex=encrypted.payload_iv_hex,
            secret_auth_tag_hex=encrypted.payload_auth_tag_hex,
            secret_fingerprint_hex=secret_fingerprint,
            event_types=event_types,
            is_active=True,
            created_at_utc=now_iso,
        )

    @classmethod
    def publish_event(
        cls,
        conn: sqlite3.Connection,
        ledger_id: str,
        event_type: str,
        payload: dict[str, Any] | str,
        event_id: str | None = None,
    ) -> OutboxEvent:
        if event_id is None:
            event_id = f"evt_{uuid.uuid4().hex[:16]}"

        if isinstance(payload, dict):
            payload_json = json.dumps(payload, separators=(",", ":"))
        else:
            payload_json = payload

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO event_outbox (ledger_id, event_id, event_type, payload_json, created_at_utc)
            VALUES (?, ?, ?, ?, ?);
            """,
            (ledger_id, event_id, event_type, payload_json, now_iso),
        )

        # Enqueue deliveries for active matching subscriptions
        cursor.execute(
            """
            SELECT subscription_id, event_types_json
            FROM webhook_subscriptions
            WHERE ledger_id = ? AND is_active = 1;
            """,
            (ledger_id,),
        )
        matching_subscriptions = []
        for sub_id, types_raw in cursor.fetchall():
            try:
                sub_types = json.loads(types_raw)
                if "*" in sub_types or event_type in sub_types:
                    matching_subscriptions.append(sub_id)
            except Exception:
                continue

        for sub_id in matching_subscriptions:
            delivery_id = f"del_{uuid.uuid4().hex[:16]}"
            cursor.execute(
                """
                INSERT INTO webhook_deliveries (
                    ledger_id, delivery_id, event_id, subscription_id,
                    status, retry_count, next_retry_at_utc, created_at_utc
                ) VALUES (?, ?, ?, ?, 'PENDING', 0, ?, ?);
                """,
                (ledger_id, delivery_id, event_id, sub_id, now_iso, now_iso),
            )

        conn.commit()
        return OutboxEvent(
            ledger_id=ledger_id,
            event_id=event_id,
            event_type=event_type,
            payload_json=payload_json,
            created_at_utc=now_iso,
        )
