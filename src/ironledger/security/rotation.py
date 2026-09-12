"""Per-tenant cryptographic key rotation and zero-downtime re-encryption engine."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ironledger.events.router import EventRouter
from ironledger.security.envelope import EnvelopeCiphertext, EnvelopeEncryptor
from ironledger.security.key_provider import EnvironmentKeyProvider, KeyProvider


class KeyRotationError(ValueError):
    """Raised when tenant key rotation encounters an error."""


class TenantKeyRotationEngine:
    """Manages zero-downtime tenant KEK rotation and background DEK re-wrapping."""

    @classmethod
    def rotate_tenant_kek(
        cls,
        conn: sqlite3.Connection,
        tenant_id: str,
        new_kek_key_id: str,
        rotated_by: str = "operator",
        key_provider: KeyProvider | None = None,
    ) -> dict[str, Any]:
        """Atomically re-wrap all webhook secrets and connector credentials under a new KEK."""
        if key_provider is None:
            key_provider = EnvironmentKeyProvider()

        # Validate that key_provider can retrieve the new KEK
        try:
            key_provider.get_key(new_kek_key_id)
        except Exception as exc:
            raise KeyRotationError(f"New KEK '{new_kek_key_id}' unavailable in key provider: {exc}") from exc

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rotation_id = f"rot_{uuid.uuid4().hex[:16]}"
        cursor = conn.cursor()

        # Record rotation in progress
        cursor.execute(
            """
            INSERT INTO tenant_key_rotations (
                rotation_id, tenant_id, kek_key_id, previous_kek_key_id,
                rewrapped_count, status, rotated_by, created_at_utc
            ) VALUES (?, ?, ?, NULL, 0, 'IN_PROGRESS', ?, ?)
            """,
            (rotation_id, tenant_id, new_kek_key_id, rotated_by, now_utc),
        )

        rewrapped_count = 0
        prev_kek_id: str | None = None

        try:
            # 1. Re-wrap Webhook Subscriptions
            cursor.execute(
                """
                SELECT ledger_id, subscription_id, kek_key_id, encrypted_dek_blob,
                       dek_iv_hex, dek_auth_tag_hex, encrypted_secret_blob,
                       secret_iv_hex, secret_auth_tag_hex
                FROM webhook_subscriptions
                """
            )
            subs = cursor.fetchall()
            for row in subs:
                l_id, s_id, old_kek, dek_blob, dek_iv, dek_tag, sec_blob, sec_iv, sec_tag = row
                if prev_kek_id is None:
                    prev_kek_id = old_kek

                # Decrypt secret under old KEK
                old_envelope = EnvelopeCiphertext(
                    kek_key_id=old_kek,
                    encrypted_dek_blob=dek_blob,
                    dek_iv_hex=dek_iv,
                    dek_auth_tag_hex=dek_tag,
                    encrypted_payload_blob=sec_blob,
                    payload_iv_hex=sec_iv,
                    payload_auth_tag_hex=sec_tag,
                )
                aad = f"{l_id}:webhook:{s_id}".encode("utf-8")
                secret_bytes = EnvelopeEncryptor.decrypt(old_envelope, key_provider, aad)

                # Re-encrypt under new KEK
                new_envelope = EnvelopeEncryptor.encrypt(
                    payload=secret_bytes,
                    kek_key_id=new_kek_key_id,
                    key_provider=key_provider,
                    aad=aad,
                )

                cursor.execute(
                    """
                    UPDATE webhook_subscriptions
                    SET kek_key_id = ?,
                        encrypted_dek_blob = ?,
                        dek_iv_hex = ?,
                        dek_auth_tag_hex = ?,
                        encrypted_secret_blob = ?,
                        secret_iv_hex = ?,
                        secret_auth_tag_hex = ?
                    WHERE ledger_id = ? AND subscription_id = ?
                    """,
                    (
                        new_envelope.kek_key_id,
                        new_envelope.encrypted_dek_blob,
                        new_envelope.dek_iv_hex,
                        new_envelope.dek_auth_tag_hex,
                        new_envelope.encrypted_payload_blob,
                        new_envelope.payload_iv_hex,
                        new_envelope.payload_auth_tag_hex,
                        l_id,
                        s_id,
                    ),
                )
                rewrapped_count += 1

            # 2. Re-wrap Connector Credentials
            cursor.execute(
                """
                SELECT ledger_id, provider_id, kek_key_id, encrypted_dek_blob,
                       dek_iv_hex, dek_auth_tag_hex, encrypted_payload_blob,
                       payload_iv_hex, payload_auth_tag_hex
                FROM connector_credentials
                """
            )
            creds = cursor.fetchall()
            for row in creds:
                l_id, p_id, old_kek, dek_blob, dek_iv, dek_tag, pay_blob, pay_iv, pay_tag = row
                if prev_kek_id is None:
                    prev_kek_id = old_kek

                old_envelope = EnvelopeCiphertext(
                    kek_key_id=old_kek,
                    encrypted_dek_blob=dek_blob,
                    dek_iv_hex=dek_iv,
                    dek_auth_tag_hex=dek_tag,
                    encrypted_payload_blob=pay_blob,
                    payload_iv_hex=pay_iv,
                    payload_auth_tag_hex=pay_tag,
                )
                aad = f"{l_id}:{p_id}".encode("utf-8")
                cred_bytes = EnvelopeEncryptor.decrypt(old_envelope, key_provider, aad)

                new_envelope = EnvelopeEncryptor.encrypt(
                    payload=cred_bytes,
                    kek_key_id=new_kek_key_id,
                    key_provider=key_provider,
                    aad=aad,
                )

                cursor.execute(
                    """
                    UPDATE connector_credentials
                    SET kek_key_id = ?,
                        encrypted_dek_blob = ?,
                        dek_iv_hex = ?,
                        dek_auth_tag_hex = ?,
                        encrypted_payload_blob = ?,
                        payload_iv_hex = ?,
                        payload_auth_tag_hex = ?
                    WHERE ledger_id = ? AND provider_id = ?
                    """,
                    (
                        new_envelope.kek_key_id,
                        new_envelope.encrypted_dek_blob,
                        new_envelope.dek_iv_hex,
                        new_envelope.dek_auth_tag_hex,
                        new_envelope.encrypted_payload_blob,
                        new_envelope.payload_iv_hex,
                        new_envelope.payload_auth_tag_hex,
                        l_id,
                        p_id,
                    ),
                )
                rewrapped_count += 1


            completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cursor.execute(
                """
                UPDATE tenant_key_rotations
                SET previous_kek_key_id = ?,
                    rewrapped_count = ?,
                    status = 'COMPLETED',
                    completed_at_utc = ?
                WHERE rotation_id = ?
                """,
                (prev_kek_id, rewrapped_count, completed_at, rotation_id),
            )

            # Emit audit alert
            EventRouter.emit_system_alert(
                conn=conn,
                ledger_id="default",
                severity="INFO",
                message=f"Tenant '{tenant_id}' KEK rotated to '{new_kek_key_id}' ({rewrapped_count} secrets re-wrapped)",
                details={
                    "rotation_id": rotation_id,
                    "tenant_id": tenant_id,
                    "new_kek_key_id": new_kek_key_id,
                    "previous_kek_key_id": prev_kek_id,
                    "rewrapped_count": rewrapped_count,
                },
                tenant_id=tenant_id,
            )

            conn.commit()
            return {
                "rotation_id": rotation_id,
                "tenant_id": tenant_id,
                "new_kek_key_id": new_kek_key_id,
                "previous_kek_key_id": prev_kek_id,
                "rewrapped_count": rewrapped_count,
                "status": "COMPLETED",
                "completed_at_utc": completed_at,
            }

        except Exception as exc:
            conn.rollback()
            cursor.execute(
                """
                UPDATE tenant_key_rotations
                SET status = 'FAILED'
                WHERE rotation_id = ?
                """,
                (rotation_id,),
            )
            conn.commit()
            raise KeyRotationError(f"Key rotation failed for tenant '{tenant_id}': {exc}") from exc
