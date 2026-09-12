"""Database helpers for envelope-encrypted connector credentials."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from ironledger.security.envelope import EnvelopeCiphertext, EnvelopeEncryptor
from ironledger.security.key_provider import KeyProvider


def save_connector_credentials(
    conn: sqlite3.Connection,
    ledger_id: str,
    provider_id: str,
    credentials_payload: dict[str, Any],
    key_provider: KeyProvider,
    kek_key_id: str = "default",
) -> str:
    """Encrypts and persists connector credentials in connector_credentials table."""
    credential_id = f"cred_{uuid.uuid4().hex[:12]}"
    payload_bytes = json.dumps(credentials_payload).encode("utf-8")
    aad = f"{ledger_id}|{provider_id}".encode("utf-8")

    envelope = EnvelopeEncryptor.encrypt(
        payload=payload_bytes,
        key_provider=key_provider,
        kek_key_id=kek_key_id,
        aad=aad,
    )

    conn.execute(
        """
        INSERT INTO connector_credentials (
            ledger_id, credential_id, provider_id, kek_key_id,
            encrypted_dek_blob, dek_iv_hex, dek_auth_tag_hex,
            encrypted_payload_blob, payload_iv_hex, payload_auth_tag_hex,
            created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(ledger_id, provider_id) DO UPDATE SET
            credential_id = excluded.credential_id,
            kek_key_id = excluded.kek_key_id,
            encrypted_dek_blob = excluded.encrypted_dek_blob,
            dek_iv_hex = excluded.dek_iv_hex,
            dek_auth_tag_hex = excluded.dek_auth_tag_hex,
            encrypted_payload_blob = excluded.encrypted_payload_blob,
            payload_iv_hex = excluded.payload_iv_hex,
            payload_auth_tag_hex = excluded.payload_auth_tag_hex,
            updated_at_utc = datetime('now')
        """,
        (
            ledger_id,
            credential_id,
            provider_id,
            envelope.kek_key_id,
            envelope.encrypted_dek_blob,
            envelope.dek_iv_hex,
            envelope.dek_auth_tag_hex,
            envelope.encrypted_payload_blob,
            envelope.payload_iv_hex,
            envelope.payload_auth_tag_hex,
        ),
    )
    return credential_id


def load_connector_credentials(
    conn: sqlite3.Connection,
    ledger_id: str,
    provider_id: str,
    key_provider: KeyProvider,
) -> dict[str, Any] | None:
    """Retrieves and decrypts connector credentials."""
    cur = conn.execute(
        """
        SELECT kek_key_id, encrypted_dek_blob, dek_iv_hex, dek_auth_tag_hex,
               encrypted_payload_blob, payload_iv_hex, payload_auth_tag_hex
        FROM connector_credentials
        WHERE ledger_id = ? AND provider_id = ?
        """,
        (ledger_id, provider_id),
    )
    row = cur.fetchone()
    if row is None:
        return None

    kek_key_id, enc_dek, dek_iv, dek_tag, enc_payload, payload_iv, payload_tag = row
    envelope = EnvelopeCiphertext(
        kek_key_id=kek_key_id,
        encrypted_dek_blob=enc_dek,
        dek_iv_hex=dek_iv,
        dek_auth_tag_hex=dek_tag,
        encrypted_payload_blob=enc_payload,
        payload_iv_hex=payload_iv,
        payload_auth_tag_hex=payload_tag,
    )

    aad = f"{ledger_id}|{provider_id}".encode("utf-8")
    decrypted_bytes = EnvelopeEncryptor.decrypt(
        envelope=envelope,
        key_provider=key_provider,
        aad=aad,
    )
    return json.loads(decrypted_bytes.decode("utf-8"))
