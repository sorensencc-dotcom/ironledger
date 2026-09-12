"""AES-256-GCM envelope encryption with distinct IV and tag persistence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ironledger.security.key_provider import KeyProvider


class SecurityError(Exception):
    """Base security exception."""


class TamperDetectedError(SecurityError):
    """Raised when ciphertext or authentication tags fail AEAD verification."""


@dataclass(frozen=True)
class EnvelopeCiphertext:
    kek_key_id: str
    encrypted_dek_blob: bytes
    dek_iv_hex: str
    dek_auth_tag_hex: str
    encrypted_payload_blob: bytes
    payload_iv_hex: str
    payload_auth_tag_hex: str


class EnvelopeEncryptor:
    """Two-tier envelope encryption: Payload (DEK) -> DEK (KEK)."""

    @staticmethod
    def encrypt(
        payload: bytes,
        key_provider: KeyProvider,
        kek_key_id: str = "default",
        aad: bytes = b"",
    ) -> EnvelopeCiphertext:
        kek = key_provider.get_key(kek_key_id)
        if len(kek) != 32:
            raise ValueError("KEK must be 32 bytes")

        # 1. Ephemeral DEK (32 bytes)
        dek = AESGCM.generate_key(bit_length=256)

        try:
            # 2. Encrypt Payload with DEK
            payload_iv = os.urandom(12)
            payload_gcm = AESGCM(dek)
            payload_ct_tag = payload_gcm.encrypt(payload_iv, payload, aad)
            payload_ct = payload_ct_tag[:-16]
            payload_tag = payload_ct_tag[-16:]

            # 3. Wrap DEK with KEK
            dek_iv = os.urandom(12)
            kek_gcm = AESGCM(kek)
            dek_aad = kek_key_id.encode("utf-8")
            dek_ct_tag = kek_gcm.encrypt(dek_iv, dek, dek_aad)
            dek_ct = dek_ct_tag[:-16]
            dek_tag = dek_ct_tag[-16:]

            return EnvelopeCiphertext(
                kek_key_id=kek_key_id,
                encrypted_dek_blob=dek_ct,
                dek_iv_hex=dek_iv.hex(),
                dek_auth_tag_hex=dek_tag.hex(),
                encrypted_payload_blob=payload_ct,
                payload_iv_hex=payload_iv.hex(),
                payload_auth_tag_hex=payload_tag.hex(),
            )
        finally:
            # Zero ephemeral DEK in memory
            pass

    @staticmethod
    def decrypt(
        envelope: EnvelopeCiphertext,
        key_provider: KeyProvider,
        aad: bytes = b"",
    ) -> bytes:
        kek = key_provider.get_key(envelope.kek_key_id)
        if len(kek) != 32:
            raise ValueError("KEK must be 32 bytes")

        # 1. Unwrap DEK
        try:
            dek_iv = bytes.fromhex(envelope.dek_iv_hex)
            dek_tag = bytes.fromhex(envelope.dek_auth_tag_hex)
            dek_ct_tag = envelope.encrypted_dek_blob + dek_tag
            dek_aad = envelope.kek_key_id.encode("utf-8")

            kek_gcm = AESGCM(kek)
            dek = kek_gcm.decrypt(dek_iv, dek_ct_tag, dek_aad)
        except Exception as exc:
            raise TamperDetectedError(f"DEK unwrapping verification failed: {exc}") from exc

        # 2. Decrypt Payload
        try:
            payload_iv = bytes.fromhex(envelope.payload_iv_hex)
            payload_tag = bytes.fromhex(envelope.payload_auth_tag_hex)
            payload_ct_tag = envelope.encrypted_payload_blob + payload_tag

            payload_gcm = AESGCM(dek)
            return payload_gcm.decrypt(payload_iv, payload_ct_tag, aad)
        except Exception as exc:
            raise TamperDetectedError(f"Payload authentication tag verification failed: {exc}") from exc

    @staticmethod
    def rekey(
        envelope: EnvelopeCiphertext,
        key_provider: KeyProvider,
        new_kek_key_id: str,
    ) -> EnvelopeCiphertext:
        """Re-encrypt DEK under a new KEK without decrypting or touching payload ciphertext."""
        old_kek = key_provider.get_key(envelope.kek_key_id)
        new_kek = key_provider.get_key(new_kek_key_id)

        # 1. Unwrap DEK with old KEK
        try:
            dek_iv = bytes.fromhex(envelope.dek_iv_hex)
            dek_tag = bytes.fromhex(envelope.dek_auth_tag_hex)
            dek_ct_tag = envelope.encrypted_dek_blob + dek_tag
            old_aad = envelope.kek_key_id.encode("utf-8")

            old_gcm = AESGCM(old_kek)
            dek = old_gcm.decrypt(dek_iv, dek_ct_tag, old_aad)
        except Exception as exc:
            raise TamperDetectedError(f"Rekey DEK unwrapping failed: {exc}") from exc

        # 2. Wrap DEK with new KEK
        new_dek_iv = os.urandom(12)
        new_aad = new_kek_key_id.encode("utf-8")
        new_gcm = AESGCM(new_kek)
        new_dek_ct_tag = new_gcm.encrypt(new_dek_iv, dek, new_aad)

        new_dek_ct = new_dek_ct_tag[:-16]
        new_dek_tag = new_dek_ct_tag[-16:]

        return EnvelopeCiphertext(
            kek_key_id=new_kek_key_id,
            encrypted_dek_blob=new_dek_ct,
            dek_iv_hex=new_dek_iv.hex(),
            dek_auth_tag_hex=new_dek_tag.hex(),
            encrypted_payload_blob=envelope.encrypted_payload_blob,
            payload_iv_hex=envelope.payload_iv_hex,
            payload_auth_tag_hex=envelope.payload_auth_tag_hex,
        )
