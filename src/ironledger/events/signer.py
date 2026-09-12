"""Webhook HMAC-SHA256 signature generator and anti-replay verification."""

from __future__ import annotations

import hmac
import hashlib
import time
from typing import Any


class WebhookSigner:
    """Computes and validates tamper-evident HMAC-SHA256 webhook signatures."""

    @classmethod
    def compute_signature_hex(
        cls,
        secret: str | bytes,
        timestamp: int,
        event_id: str,
        delivery_id: str,
        payload_json: str,
    ) -> str:
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        else:
            secret_bytes = secret

        sign_input = f"{timestamp}.{event_id}.{delivery_id}.{payload_json}".encode("utf-8")
        return hmac.new(secret_bytes, sign_input, hashlib.sha256).hexdigest()

    @classmethod
    def build_signature_header(
        cls,
        secret: str | bytes,
        timestamp: int,
        event_id: str,
        delivery_id: str,
        payload_json: str,
    ) -> str:
        sig_hex = cls.compute_signature_hex(secret, timestamp, event_id, delivery_id, payload_json)
        return f"t={timestamp},e={event_id},d={delivery_id},v1={sig_hex}"

    @classmethod
    def build_headers(
        cls,
        secret: str | bytes,
        timestamp: int,
        event_id: str,
        delivery_id: str,
        payload_json: str,
    ) -> dict[str, str]:
        header_sig = cls.build_signature_header(secret, timestamp, event_id, delivery_id, payload_json)
        return {
            "Content-Type": "application/json",
            "X-IronLedger-Timestamp": str(timestamp),
            "X-IronLedger-Event-Id": event_id,
            "X-IronLedger-Delivery-Id": delivery_id,
            "X-IronLedger-Signature": header_sig,
        }


    @classmethod
    def verify_signature(
        cls,
        secret: str | bytes,
        signature_header: str,
        payload_json: str,
        tolerance_seconds: int = 300,
        current_time: int | None = None,
    ) -> bool:
        if current_time is None:
            current_time = int(time.time())

        parts: dict[str, str] = {}
        for item in signature_header.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip()] = v.strip()

        t_str = parts.get("t")
        event_id = parts.get("e")
        delivery_id = parts.get("d")
        v1_sig = parts.get("v1")

        if not (t_str and event_id and delivery_id and v1_sig):
            return False

        try:
            timestamp = int(t_str)
        except ValueError:
            return False

        if abs(current_time - timestamp) > tolerance_seconds:
            return False

        expected_sig = cls.compute_signature_hex(secret, timestamp, event_id, delivery_id, payload_json)
        return hmac.compare_digest(expected_sig, v1_sig)
