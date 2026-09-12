"""Federated event router and atomic outbox emitter."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Final

from ironledger.events.envelope import (
    FederatedEvent,
    canonical_event_bytes,
    compute_event_id,
    validate_federated_event,
)


class EventRouter:
    """Publishes canonical gov.event.v1 envelopes into outbox and audit trails."""

    @staticmethod
    def publish(conn: sqlite3.Connection, event: FederatedEvent) -> str:
        """Atomically persist a federated event into outbox and governance audit log."""
        validate_federated_event(event)

        canonical_bytes = canonical_event_bytes(event)
        envelope_hash = hashlib.sha256(canonical_bytes).hexdigest()

        cursor = conn.cursor()

        # 1. Insert into federated_event_outbox
        cursor.execute(
            """
            INSERT INTO federated_event_outbox (
                event_id, tenant_id, ledger_id, event_type, source, severity,
                payload_json, metadata_json, published_to_peers, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                event.event_id,
                event.tenant_id,
                event.ledger_id,
                event.event_type,
                event.source,
                event.severity,
                json.dumps(event.payload, sort_keys=True),
                json.dumps(event.metadata, sort_keys=True),
                event.recorded_at,
            ),
        )

        # 2. Mirror into governance_audit_events
        cursor.execute(
            """
            INSERT INTO governance_audit_events (
                ledger_id, actor, action, target, before_state_json, after_state_json,
                envelope_hash, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.ledger_id,
                f"event_router:{event.source}",
                event.event_type,
                f"event:{event.event_id}",
                "{}",
                json.dumps(event.payload, sort_keys=True),
                envelope_hash,
                event.recorded_at,
            ),
        )

        return event.event_id

    @classmethod
    def emit_compliance_bundle_created(
        cls,
        conn: sqlite3.Connection,
        ledger_id: str,
        bundle_id: str,
        framework: str,
        merkle_root_hex: str,
        archive_sha256: str,
        record_count: int,
        tenant_id: str = "default",
    ) -> str:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "bundle_id": bundle_id,
            "framework": framework,
            "merkle_root": merkle_root_hex,
            "bundle_hash": archive_sha256,
            "record_count": record_count,
            "verification_status": "VERIFIED",
        }
        event_id = compute_event_id("COMPLIANCE_BUNDLE_CREATED", tenant_id, ledger_id, now_utc, payload)
        event = FederatedEvent(
            event_id=event_id,
            event_type="COMPLIANCE_BUNDLE_CREATED",
            occurred_at=now_utc,
            recorded_at=now_utc,
            tenant_id=tenant_id,
            ledger_id=ledger_id,
            source="compliance",
            severity="INFO",
            payload=payload,
        )
        return cls.publish(conn, event)

    @classmethod
    def emit_anomaly_flagged(
        cls,
        conn: sqlite3.Connection,
        ledger_id: str,
        flag_id: str,
        rule_type: str,
        staged_tx_id: str,
        score_num: int,
        score_den: int,
        severity: str = "WARN",
        tenant_id: str = "default",
    ) -> str:

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "flag_id": flag_id,
            "rule_type": rule_type,
            "staged_tx_id": staged_tx_id,
            "score_numerator": score_num,
            "score_denominator": score_den,
            "resolution_status": "UNRESOLVED",
        }
        event_id = compute_event_id("ANOMALY_FLAGGED", tenant_id, ledger_id, now_utc, payload)
        event = FederatedEvent(
            event_id=event_id,
            event_type="ANOMALY_FLAGGED",
            occurred_at=now_utc,
            recorded_at=now_utc,
            tenant_id=tenant_id,
            ledger_id=ledger_id,
            source="anomaly",
            severity=severity,
            payload=payload,
        )
        return cls.publish(conn, event)

    @classmethod
    def emit_replication_advanced(
        cls,
        conn: sqlite3.Connection,
        ledger_id: str,
        wal_magic: str,
        frame_index: int,
        commit_page_count: int,
        tenant_id: str = "default",
    ) -> str:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "wal_magic": wal_magic,
            "frame_index": frame_index,
            "commit_page_count": commit_page_count,
            "status": "IN_SYNC",
        }
        event_id = compute_event_id("REPLICATION_POSITION_ADVANCED", tenant_id, ledger_id, now_utc, payload)
        event = FederatedEvent(
            event_id=event_id,
            event_type="REPLICATION_POSITION_ADVANCED",
            occurred_at=now_utc,
            recorded_at=now_utc,
            tenant_id=tenant_id,
            ledger_id=ledger_id,
            source="replication",
            severity="INFO",
            payload=payload,
        )
        return cls.publish(conn, event)

    @classmethod
    def emit_system_alert(
        cls,
        conn: sqlite3.Connection,
        ledger_id: str,
        message: str,
        details: dict[str, Any] | None = None,
        severity: str = "WARN",
        tenant_id: str = "default",
    ) -> str:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "message": message,
            "details": details or {},
        }
        event_id = compute_event_id("SYSTEM_ALERT", tenant_id, ledger_id, now_utc, payload)
        event = FederatedEvent(
            event_id=event_id,
            event_type="SYSTEM_ALERT",
            occurred_at=now_utc,
            recorded_at=now_utc,
            tenant_id=tenant_id,
            ledger_id=ledger_id,
            source="system",
            severity=severity,
            payload=payload,
        )
        return cls.publish(conn, event)

