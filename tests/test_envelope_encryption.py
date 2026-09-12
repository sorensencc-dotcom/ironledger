"""Comprehensive test suite for Phase 9 envelope encryption, key providers, and secret scrubbing."""

from __future__ import annotations

import os
import sqlite3
import pytest

from ironledger.db.migrations import migrate_governed
from ironledger.security.credentials import (
    load_connector_credentials,
    save_connector_credentials,
)
from ironledger.security.envelope import (
    EnvelopeCiphertext,
    EnvelopeEncryptor,
    TamperDetectedError,
)
from ironledger.security.key_provider import (
    EnvironmentKeyProvider,
    KeyNotFoundError,
    WindowsDpapiProvider,
)
from ironledger.security.scrubbing import SecretScrubber


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    migrate_governed(conn)
    # Insert prerequisite ledger and provider
    conn.execute(
        """
        INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency, created_at, root_account, storage_root, is_active)
        VALUES ('ledger_tenant_1', 'Tenant 1', 'USD', datetime('now'), 'Assets', 't1', 1)
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO connector_providers (provider_id, name, protocol_type, base_url)
        VALUES ('prov_plaid_test', 'Plaid Test Provider', 'PLAID', 'https://api.plaid.com')
        """
    )
    conn.commit()
    return conn


@pytest.fixture
def env_key_provider(monkeypatch):
    test_kek = os.urandom(32).hex()
    monkeypatch.setenv("IRONLEDGER_KEK_DEFAULT", test_kek)
    monkeypatch.setenv("IRONLEDGER_KEK_BACKUP", os.urandom(32).hex())
    return EnvironmentKeyProvider()


# ============================================================================
# 1. Key Provider Tests
# ============================================================================


def test_environment_key_provider_resolution(env_key_provider: EnvironmentKeyProvider):
    key_default = env_key_provider.get_key("default")
    assert len(key_default) == 32

    key_backup = env_key_provider.get_key("backup")
    assert len(key_backup) == 32
    assert key_default != key_backup

    with pytest.raises(KeyNotFoundError):
        env_key_provider.get_key("nonexistent_key_id")


def test_key_rotation_in_provider(env_key_provider: EnvironmentKeyProvider):
    new_key = os.urandom(32)
    env_key_provider.rotate_key("rotated_kek", new_key)
    retrieved = env_key_provider.get_key("rotated_kek")
    assert retrieved == new_key


def test_dpapi_provider_roundtrip(tmp_path):
    provider = WindowsDpapiProvider(key_storage_dir=tmp_path / "keys")
    key1 = provider.get_key("master_key_1")
    assert len(key1) == 32

    # Second load from same storage dir should retrieve identical key
    provider2 = WindowsDpapiProvider(key_storage_dir=tmp_path / "keys")
    key2 = provider2.get_key("master_key_1")
    assert key1 == key2


# ============================================================================
# 2. Envelope Encryption & Tamper Detection Tests
# ============================================================================


def test_envelope_encryption_roundtrip(env_key_provider: EnvironmentKeyProvider):
    payload = b"sensitive-banking-credentials-client-secret-12345"
    aad = b"ledger_tenant_1|prov_plaid_test"

    envelope = EnvelopeEncryptor.encrypt(
        payload=payload,
        key_provider=env_key_provider,
        kek_key_id="default",
        aad=aad,
    )

    assert envelope.kek_key_id == "default"
    assert len(envelope.encrypted_dek_blob) == 32
    assert len(envelope.dek_iv_hex) == 24
    assert len(envelope.dek_auth_tag_hex) == 32
    assert len(envelope.payload_iv_hex) == 24
    assert len(envelope.payload_auth_tag_hex) == 32
    assert envelope.encrypted_payload_blob != payload

    decrypted = EnvelopeEncryptor.decrypt(
        envelope=envelope,
        key_provider=env_key_provider,
        aad=aad,
    )
    assert decrypted == payload


def test_envelope_tamper_detection(env_key_provider: EnvironmentKeyProvider):
    payload = b"super-secret-token"
    aad = b"ledger_tenant_1|prov_plaid_test"

    envelope = EnvelopeEncryptor.encrypt(
        payload=payload,
        key_provider=env_key_provider,
        kek_key_id="default",
        aad=aad,
    )

    # 1. Tamper with payload ciphertext
    tampered_payload_ct = bytearray(envelope.encrypted_payload_blob)
    tampered_payload_ct[0] ^= 0xFF
    env_tampered_ct = EnvelopeCiphertext(
        kek_key_id=envelope.kek_key_id,
        encrypted_dek_blob=envelope.encrypted_dek_blob,
        dek_iv_hex=envelope.dek_iv_hex,
        dek_auth_tag_hex=envelope.dek_auth_tag_hex,
        encrypted_payload_blob=bytes(tampered_payload_ct),
        payload_iv_hex=envelope.payload_iv_hex,
        payload_auth_tag_hex=envelope.payload_auth_tag_hex,
    )
    with pytest.raises(TamperDetectedError):
        EnvelopeEncryptor.decrypt(env_tampered_ct, env_key_provider, aad=aad)

    # 2. Tamper with DEK ciphertext
    tampered_dek = bytearray(envelope.encrypted_dek_blob)
    tampered_dek[0] ^= 0xFF
    env_tampered_dek = EnvelopeCiphertext(
        kek_key_id=envelope.kek_key_id,
        encrypted_dek_blob=bytes(tampered_dek),
        dek_iv_hex=envelope.dek_iv_hex,
        dek_auth_tag_hex=envelope.dek_auth_tag_hex,
        encrypted_payload_blob=envelope.encrypted_payload_blob,
        payload_iv_hex=envelope.payload_iv_hex,
        payload_auth_tag_hex=envelope.payload_auth_tag_hex,
    )
    with pytest.raises(TamperDetectedError):
        EnvelopeEncryptor.decrypt(env_tampered_dek, env_key_provider, aad=aad)

    # 3. Tamper with AAD (tenant boundary mismatch)
    wrong_aad = b"ledger_tenant_OTHER|prov_plaid_test"
    with pytest.raises(TamperDetectedError):
        EnvelopeEncryptor.decrypt(envelope, env_key_provider, aad=wrong_aad)


def test_envelope_rekey_without_payload_alteration(env_key_provider: EnvironmentKeyProvider):
    payload = b"unaltered-secret-payload"
    aad = b"ledger_tenant_1|prov_plaid_test"

    envelope_old = EnvelopeEncryptor.encrypt(
        payload=payload,
        key_provider=env_key_provider,
        kek_key_id="default",
        aad=aad,
    )

    # Rekey under 'backup' KEK
    envelope_new = EnvelopeEncryptor.rekey(
        envelope=envelope_old,
        key_provider=env_key_provider,
        new_kek_key_id="backup",
    )

    assert envelope_new.kek_key_id == "backup"
    assert envelope_new.encrypted_payload_blob == envelope_old.encrypted_payload_blob
    assert envelope_new.payload_iv_hex == envelope_old.payload_iv_hex
    assert envelope_new.payload_auth_tag_hex == envelope_old.payload_auth_tag_hex

    # Decrypt with new KEK
    decrypted = EnvelopeEncryptor.decrypt(envelope_new, env_key_provider, aad=aad)
    assert decrypted == payload


# ============================================================================
# 3. Secret Scrubber Tests
# ============================================================================


def test_secret_scrubbing_text():
    sample = (
        "User 4111111111111111 used token il_cap_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef "
        "and header Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    )
    scrubbed = SecretScrubber.scrub_text(sample)
    assert "4111111111111111" not in scrubbed
    assert "[REDACTED_PAN]" in scrubbed
    assert "il_cap_[REDACTED_TOKEN]" in scrubbed
    assert "Bearer [REDACTED]" in scrubbed


def test_secret_scrubbing_dict():
    nested_data = {
        "user_id": "usr_99",
        "client_secret": "super_secret_value",
        "api_key": "key_123456",
        "metadata": {
            "card_number": "4111 1111 1111 1111",
            "safe_field": "public_data",
        },
        "log_messages": [
            "Generated token access-sandbox-12345-abcdef",
        ],
    }
    scrubbed = SecretScrubber.scrub_dict(nested_data)
    assert scrubbed["user_id"] == "usr_99"
    assert scrubbed["client_secret"] == "[REDACTED]"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["metadata"]["safe_field"] == "public_data"
    assert "[REDACTED_PAN]" in scrubbed["metadata"]["card_number"]
    assert "access-sandbox-[REDACTED]" in scrubbed["log_messages"][0]


# ============================================================================
# 4. Database Persistence Tests
# ============================================================================


def test_credentials_database_persistence(db_conn: sqlite3.Connection, env_key_provider: EnvironmentKeyProvider):
    creds_payload = {
        "client_id": "plaid_client_001",
        "secret": "plaid_secret_xyz",
        "access_token": "access-sandbox-999888",
    }

    cred_id = save_connector_credentials(
        conn=db_conn,
        ledger_id="ledger_tenant_1",
        provider_id="prov_plaid_test",
        credentials_payload=creds_payload,
        key_provider=env_key_provider,
        kek_key_id="default",
    )
    assert cred_id.startswith("cred_")

    # Verify zero plaintext stored in database
    cur = db_conn.execute("SELECT encrypted_payload_blob, kek_key_id FROM connector_credentials WHERE credential_id = ?", (cred_id,))
    row = cur.fetchone()
    assert row is not None
    assert b"plaid_secret_xyz" not in row[0]
    assert row[1] == "default"

    # Load and decrypt
    loaded = load_connector_credentials(
        conn=db_conn,
        ledger_id="ledger_tenant_1",
        provider_id="prov_plaid_test",
        key_provider=env_key_provider,
    )
    assert loaded is not None
    assert loaded["client_id"] == "plaid_client_001"
    assert loaded["secret"] == "plaid_secret_xyz"
    assert loaded["access_token"] == "access-sandbox-999888"

    # Cross-tenant isolation: another tenant cannot load credentials
    tenant_2_loaded = load_connector_credentials(
        conn=db_conn,
        ledger_id="ledger_tenant_2",
        provider_id="prov_plaid_test",
        key_provider=env_key_provider,
    )
    assert tenant_2_loaded is None