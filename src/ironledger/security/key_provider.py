"""Key Provider abstractions and implementations for envelope encryption."""

from __future__ import annotations

import abc
import base64
import ctypes
import os
import pathlib
from typing import Any


class KeyProviderError(Exception):
    """Base exception for key provider failures."""


class KeyNotFoundError(KeyProviderError):
    """Raised when requested KEK key_id is not found."""


class KeyProvider(abc.ABC):
    """Abstract base class for Key Encryption Key (KEK) providers."""

    @abc.abstractmethod
    def get_key(self, key_id: str) -> bytes:
        """Retrieve 256-bit (32-byte) KEK by key_id."""

    @abc.abstractmethod
    def rotate_key(self, key_id: str, new_key: bytes) -> None:
        """Store or rotate KEK for given key_id."""


class EnvironmentKeyProvider(KeyProvider):
    """Key provider resolving KEKs from environment variables."""

    def __init__(self, key_prefix: str = "IRONLEDGER_KEK_"):
        self.key_prefix = key_prefix
        self._in_memory_keys: dict[str, bytes] = {}

    def _normalize_key(self, raw_val: str) -> bytes:
        raw_val = raw_val.strip()
        # Try hex decoding (64 hex chars = 32 bytes)
        if len(raw_val) == 64:
            try:
                return bytes.fromhex(raw_val)
            except ValueError:
                pass
        # Try base64 decoding (44 chars = 32 bytes)
        try:
            decoded = base64.b64decode(raw_val)
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass
        # Raw bytes if 32 bytes
        val_bytes = raw_val.encode("utf-8")
        if len(val_bytes) == 32:
            return val_bytes
        raise KeyProviderError("KEK must resolve to exactly 32 bytes (256-bit)")

    def get_key(self, key_id: str) -> bytes:
        if key_id in self._in_memory_keys:
            return self._in_memory_keys[key_id]

        env_name = f"{self.key_prefix}{key_id.upper()}"
        val = os.environ.get(env_name)
        if val is None and key_id == "default":
            val = os.environ.get("IRONLEDGER_KEK_DEFAULT")

        if val is None:
            raise KeyNotFoundError(f"Key '{key_id}' not found in environment variable '{env_name}'")

        return self._normalize_key(val)

    def rotate_key(self, key_id: str, new_key: bytes) -> None:
        if len(new_key) != 32:
            raise ValueError("New key must be exactly 32 bytes")
        self._in_memory_keys[key_id] = new_key
        os.environ[f"{self.key_prefix}{key_id.upper()}"] = new_key.hex()


class WindowsDpapiProvider(KeyProvider):
    """Windows Data Protection API (DPAPI) backed key provider."""

    def __init__(self, key_storage_dir: str | pathlib.Path = ".ironledger/keys"):
        self.storage_dir = pathlib.Path(key_storage_dir)
        self._memory_cache: dict[str, bytes] = {}

    def _protect_dpapi(self, data: bytes) -> bytes:
        if os.name != "nt":
            # Fallback for non-Windows test environments
            return b"dpapi_sim:" + base64.b64encode(data)

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]

        blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
        blob_out = DATA_BLOB()

        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        res = crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "IronLedger_KEK",
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        )
        if not res:
            raise KeyProviderError("CryptProtectData failed on Windows")

        out_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.LocalFree(blob_out.pbData)
        return out_bytes

    def _unprotect_dpapi(self, encrypted_data: bytes) -> bytes:
        if os.name != "nt":
            if encrypted_data.startswith(b"dpapi_sim:"):
                return base64.b64decode(encrypted_data[10:])
            return encrypted_data

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]

        blob_in = DATA_BLOB(len(encrypted_data), ctypes.create_string_buffer(encrypted_data, len(encrypted_data)))
        blob_out = DATA_BLOB()

        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        res = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        )
        if not res:
            raise KeyProviderError("CryptUnprotectData failed on Windows")

        out_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.LocalFree(blob_out.pbData)
        return out_bytes

    def get_key(self, key_id: str) -> bytes:
        if key_id in self._memory_cache:
            return self._memory_cache[key_id]

        key_file = self.storage_dir / f"{key_id}.dpapi"
        if not key_file.exists():
            # Generate new KEK and persist protected with DPAPI
            new_key = os.urandom(32)
            self.rotate_key(key_id, new_key)
            return new_key

        encrypted_blob = key_file.read_bytes()
        plain_key = self._unprotect_dpapi(encrypted_blob)
        if len(plain_key) != 32:
            raise KeyProviderError(f"DPAPI key '{key_id}' corrupted (length: {len(plain_key)})")
        self._memory_cache[key_id] = plain_key
        return plain_key

    def rotate_key(self, key_id: str, new_key: bytes) -> None:
        if len(new_key) != 32:
            raise ValueError("New key must be exactly 32 bytes")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        encrypted_blob = self._protect_dpapi(new_key)
        key_file = self.storage_dir / f"{key_id}.dpapi"
        key_file.write_bytes(encrypted_blob)
        self._memory_cache[key_id] = new_key
