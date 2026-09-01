"""Append-only audit chain definitions, event envelopes, and verification.

IronLedger audit events are append-only, monotonic, and hash-chained.
Every event carries a sequence number (1-based, gapless), UTC timestamp,
actor, action, target, result, optional projection version, optional
compile run reference, optional input/output hashes, previous event hash,
and canonical event hash (SHA-256).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Final

from ironledger.conventions import ConventionError, validate_utc_timestamp

__all__ = [
    "AuditVerificationError",
    "AuditEvent",
    "AuditVerificationResult",
    "GENESIS_PREV_HASH",
    "canonical_event_bytes",
    "compute_event_hash",
    "append_audit_event",
    "load_audit_events",
    "verify_audit_chain",
]

GENESIS_PREV_HASH: Final[str] = "0" * 64
VALID_RESULTS: Final[tuple[str, ...]] = ("ok", "denied", "error")


class AuditVerificationError(ValueError):
    """An audit event chain failed verification due to gap, tamper, or reordering."""


@dataclass(frozen=True)
class AuditEvent:
    """Canonical audit event envelope."""

    seq: int
    ts_utc: str
    actor: str
    action: str
    target: str
    result: str
    projection_version: str | None = None
    compile_run_id: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    prev_event_hash: str = GENESIS_PREV_HASH
    event_hash: str = ""


@dataclass(frozen=True)
class AuditVerificationResult:
    """Summary of audit chain verification."""

    is_valid: bool
    event_count: int
    head_hash: str | None


def canonical_event_bytes(event: AuditEvent | dict[str, Any]) -> bytes:
    """Return deterministic canonical UTF-8 bytes for the 11 audit event payload fields."""
    if isinstance(event, AuditEvent):
        data = asdict(event)
    elif isinstance(event, dict):
        data = dict(event)
    else:
        raise TypeError("event must be an AuditEvent instance or dict")

    payload = {
        "seq": data["seq"],
        "ts_utc": data["ts_utc"],
        "actor": data["actor"],
        "action": data["action"],
        "target": data["target"],
        "result": data["result"],
        "projection_version": data.get("projection_version"),
        "compile_run_id": data.get("compile_run_id"),
        "input_hash": data.get("input_hash"),
        "output_hash": data.get("output_hash"),
        "prev_event_hash": data["prev_event_hash"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded.encode("utf-8")


def compute_event_hash(event: AuditEvent | dict[str, Any]) -> str:
    """Compute the canonical SHA-256 digest of an audit event payload."""
    return hashlib.sha256(canonical_event_bytes(event)).hexdigest()


def append_audit_event(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    target: str,
    result: str,
    ts_utc: str | None = None,
    projection_version: str | None = None,
    compile_run_id: str | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
) -> AuditEvent:
    """Allocate the next monotonic sequence, compute the hash chain, and record the event."""
    if result not in VALID_RESULTS:
        raise ValueError(f"result {result!r} is not one of {VALID_RESULTS}")

    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(ts_utc)

    cursor = conn.execute(
        "SELECT seq, event_hash FROM audit_events ORDER BY seq DESC LIMIT 1"
    )
    last_row = cursor.fetchone()
    if last_row is None:
        next_seq = 1
        prev_hash = GENESIS_PREV_HASH
    else:
        last_seq, last_hash = last_row
        next_seq = last_seq + 1
        prev_hash = last_hash

    event_payload = AuditEvent(
        seq=next_seq,
        ts_utc=ts_utc,
        actor=actor,
        action=action,
        target=target,
        result=result,
        projection_version=projection_version,
        compile_run_id=compile_run_id,
        input_hash=input_hash,
        output_hash=output_hash,
        prev_event_hash=prev_hash,
    )
    event_hash = compute_event_hash(event_payload)
    event = AuditEvent(
        seq=next_seq,
        ts_utc=ts_utc,
        actor=actor,
        action=action,
        target=target,
        result=result,
        projection_version=projection_version,
        compile_run_id=compile_run_id,
        input_hash=input_hash,
        output_hash=output_hash,
        prev_event_hash=prev_hash,
        event_hash=event_hash,
    )

    conn.execute(
        "INSERT INTO audit_events "
        "(seq, ts_utc, actor, action, target, result, projection_version, "
        " compile_run_id, input_hash, output_hash, prev_event_hash, event_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.seq,
            event.ts_utc,
            event.actor,
            event.action,
            event.target,
            event.result,
            event.projection_version,
            event.compile_run_id,
            event.input_hash,
            event.output_hash,
            event.prev_event_hash,
            event.event_hash,
        ),
    )
    return event


def load_audit_events(conn: sqlite3.Connection) -> list[AuditEvent]:
    """Load all audit events from the database ordered by sequence."""
    cursor = conn.execute(
        "SELECT seq, ts_utc, actor, action, target, result, projection_version, "
        "compile_run_id, input_hash, output_hash, prev_event_hash, event_hash "
        "FROM audit_events ORDER BY seq ASC"
    )
    rows = cursor.fetchall()
    return [
        AuditEvent(
            seq=row[0],
            ts_utc=row[1],
            actor=row[2],
            action=row[3],
            target=row[4],
            result=row[5],
            projection_version=row[6],
            compile_run_id=row[7],
            input_hash=row[8],
            output_hash=row[9],
            prev_event_hash=row[10],
            event_hash=row[11],
        )
        for row in rows
    ]


def verify_audit_chain(
    source: list[AuditEvent] | list[dict[str, Any]] | sqlite3.Connection,
) -> AuditVerificationResult:
    """Verify an audit event chain from genesis through head hash.

    Validates:
    - Sequence is 1-based, strictly monotonic, and gapless.
    - Genesis event (seq=1) references GENESIS_PREV_HASH.
    - Each subsequent event (seq > 1) correctly references the previous event's hash.
    - Every event hash matches the canonical SHA-256 payload computation.
    - Every timestamp is valid UTC ISO-8601 with trailing Z.
    - Results and hash lengths comply with schema invariants.

    Raises :class:`AuditVerificationError` on any verification failure.
    """
    if isinstance(source, sqlite3.Connection):
        events = load_audit_events(source)
    else:
        events = source

    if not events:
        return AuditVerificationResult(is_valid=True, event_count=0, head_hash=None)

    expected_prev_hash = GENESIS_PREV_HASH
    for index, item in enumerate(events):
        expected_seq = index + 1
        if isinstance(item, AuditEvent):
            event = item
        elif isinstance(item, dict):
            event = AuditEvent(**item)
        else:
            raise AuditVerificationError(f"invalid item type in event sequence: {type(item)}")

        if event.seq != expected_seq:
            raise AuditVerificationError(
                f"sequence gap or reordering at index {index}: expected seq {expected_seq}, found {event.seq}"
            )

        if event.prev_event_hash != expected_prev_hash:
            raise AuditVerificationError(
                f"broken hash link at seq {event.seq}: expected prev_event_hash {expected_prev_hash}, "
                f"found {event.prev_event_hash}"
            )

        computed_hash = compute_event_hash(event)
        if event.event_hash != computed_hash:
            raise AuditVerificationError(
                f"hash mismatch at seq {event.seq}: stored {event.event_hash}, computed {computed_hash}"
            )

        try:
            validate_utc_timestamp(event.ts_utc)
        except ConventionError as exc:
            raise AuditVerificationError(f"invalid timestamp at seq {event.seq}: {exc}") from exc

        if event.result not in VALID_RESULTS:
            raise AuditVerificationError(
                f"invalid result at seq {event.seq}: {event.result!r} is not one of {VALID_RESULTS}"
            )

        expected_prev_hash = event.event_hash

    return AuditVerificationResult(
        is_valid=True,
        event_count=len(events),
        head_hash=events[-1].event_hash if isinstance(events[-1], AuditEvent) else events[-1]["event_hash"],
    )
