"""Event models and dataclasses for the IronLedger event notification fabric."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class OutboxEvent:
    """Immutable event stored in the transactional event outbox."""

    ledger_id: str
    event_id: str
    event_type: str
    payload_json: str
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ"))


@dataclass(frozen=True)
class WebhookSubscription:
    """Registered webhook endpoint with envelope-encrypted shared secret."""

    ledger_id: str
    subscription_id: str
    target_url: str
    kek_key_id: str
    encrypted_dek_blob: bytes
    dek_iv_hex: str
    dek_auth_tag_hex: str
    encrypted_secret_blob: bytes
    secret_iv_hex: str
    secret_auth_tag_hex: str
    secret_fingerprint_hex: str
    event_types: list[str]
    is_active: bool = True
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ"))


@dataclass
class WebhookDelivery:
    """Per-subscription webhook delivery execution record."""

    ledger_id: str
    delivery_id: str
    event_id: str
    subscription_id: str
    status: str = "PENDING"
    retry_count: int = 0
    next_retry_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ"))
    leased_by: str | None = None
    leased_until_utc: str | None = None
    last_status_code: int | None = None
    last_error: str | None = None
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ"))
    completed_at_utc: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    """Result of attempting a webhook delivery."""

    success: bool
    status_code: int | None = None
    error: str | None = None
    should_retry: bool = False
