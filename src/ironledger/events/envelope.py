"""Canonical federated event envelope (gov.event.v1).

Standardizes event representation across compliance, anomaly, replication,
connectors, and webhooks for multi-tenant federation and audit propagation.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Final

from ironledger.conventions import ConventionError, validate_utc_timestamp


SCHEMA_VERSION: Final[str] = "gov.event.v1"
VALID_SOURCES: Final[tuple[str, ...]] = (
    "compliance",
    "anomaly",
    "replication",
    "connector",
    "webhook",
    "system",
)
VALID_SEVERITIES: Final[tuple[str, ...]] = ("INFO", "WARN", "ERROR", "CRITICAL")

# Domain Event Types
EVENT_TYPES_COMPLIANCE: Final[tuple[str, ...]] = (
    "COMPLIANCE_BUNDLE_CREATED",
    "COMPLIANCE_BUNDLE_VERIFIED",
    "COMPLIANCE_BUNDLE_TAMPER_DETECTED",
)
EVENT_TYPES_ANOMALY: Final[tuple[str, ...]] = (
    "ANOMALY_FLAGGED",
    "ANOMALY_RESOLVED",
)
EVENT_TYPES_REPLICATION: Final[tuple[str, ...]] = (
    "REPLICATION_POSITION_ADVANCED",
    "REPLICATION_LAG_DETECTED",
    "REPLICATION_FAILOVER_ELECTED",
)
EVENT_TYPES_CONNECTOR: Final[tuple[str, ...]] = (
    "CONNECTOR_STATE_CHANGED",
    "CONNECTOR_CIRCUIT_BREAKER_TRIPPED",
    "CONNECTOR_SYNC_COMPLETED",
)
EVENT_TYPES_WEBHOOK: Final[tuple[str, ...]] = (
    "WEBHOOK_SUBSCRIPTION_UPDATED",
    "WEBHOOK_DLQ_REDRIVE_REQUESTED",
    "WEBHOOK_DLQ_REDRIVE_COMPLETED",
)

ALL_EVENT_TYPES: Final[tuple[str, ...]] = (
    EVENT_TYPES_COMPLIANCE
    + EVENT_TYPES_ANOMALY
    + EVENT_TYPES_REPLICATION
    + EVENT_TYPES_CONNECTOR
    + EVENT_TYPES_WEBHOOK
)


class EventEnvelopeError(ValueError):
    """Raised when a federated event envelope fails schema validation."""


@dataclass(frozen=True)
class FederatedEvent:
    """Canonical gov.event.v1 envelope."""

    event_id: str
    event_type: str
    occurred_at: str
    recorded_at: str
    tenant_id: str
    ledger_id: str
    source: str
    severity: str
    payload: dict[str, Any]
    event_version: str = "1.0.0"
    correlation_id: str | None = None
    causation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def canonical_event_bytes(event: FederatedEvent | dict[str, Any]) -> bytes:
    """Return deterministic canonical UTF-8 bytes for an event."""
    data = asdict(event) if isinstance(event, FederatedEvent) else dict(event)
    payload_dict = {
        "event_id": data["event_id"],
        "event_type": data["event_type"],
        "event_version": data.get("event_version", "1.0.0"),
        "occurred_at": data["occurred_at"],
        "recorded_at": data["recorded_at"],
        "tenant_id": data["tenant_id"],
        "ledger_id": data["ledger_id"],
        "source": data["source"],
        "severity": data["severity"],
        "correlation_id": data.get("correlation_id"),
        "causation_id": data.get("causation_id"),
        "payload": data["payload"],
        "metadata": data.get("metadata", {}),
    }
    encoded = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded.encode("utf-8")


def compute_event_id(
    event_type: str,
    tenant_id: str,
    ledger_id: str,
    occurred_at: str,
    payload: dict[str, Any],
) -> str:
    """Generate a deterministic SHA-256 event fingerprint."""
    raw = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "ledger_id": ledger_id,
        "occurred_at": occurred_at,
        "payload": payload,
    }
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:32]


def validate_federated_event(event: FederatedEvent | dict[str, Any]) -> None:
    """Validate a gov.event.v1 envelope against domain invariants."""
    data = asdict(event) if isinstance(event, FederatedEvent) else dict(event)

    for req in ("event_id", "event_type", "occurred_at", "recorded_at", "tenant_id", "ledger_id", "source", "severity", "payload"):
        if req not in data or data[req] is None:
            raise EventEnvelopeError(f"Missing required envelope field: {req}")

    if data["source"] not in VALID_SOURCES:
        raise EventEnvelopeError(f"Invalid source '{data['source']}'. Must be one of {VALID_SOURCES}")

    if data["severity"] not in VALID_SEVERITIES:
        raise EventEnvelopeError(f"Invalid severity '{data['severity']}'. Must be one of {VALID_SEVERITIES}")

    validate_utc_timestamp(data["occurred_at"])
    validate_utc_timestamp(data["recorded_at"])

    # Domain Payload Type Verification
    event_type = data["event_type"]
    payload = data["payload"]
    if not isinstance(payload, dict):
        raise EventEnvelopeError("payload must be a JSON object (dict)")

    if event_type in EVENT_TYPES_COMPLIANCE:
        if "bundle_id" not in payload:
            raise EventEnvelopeError(f"{event_type} payload requires 'bundle_id'")
    elif event_type in EVENT_TYPES_ANOMALY:
        if "flag_id" not in payload or "rule_type" not in payload:
            raise EventEnvelopeError(f"{event_type} payload requires 'flag_id' and 'rule_type'")
    elif event_type in EVENT_TYPES_REPLICATION:
        if "wal_magic" not in payload or "frame_index" not in payload:
            raise EventEnvelopeError(f"{event_type} payload requires 'wal_magic' and 'frame_index'")
    elif event_type in EVENT_TYPES_CONNECTOR:
        if "provider_id" not in payload:
            raise EventEnvelopeError(f"{event_type} payload requires 'provider_id'")
    elif event_type in EVENT_TYPES_WEBHOOK:
        if "subscription_id" not in payload:
            raise EventEnvelopeError(f"{event_type} payload requires 'subscription_id'")
