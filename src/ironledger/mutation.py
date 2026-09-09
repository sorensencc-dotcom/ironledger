"""Append-only mutation ledger definitions, event envelopes, and verification.

IronLedger mutation events track first-class ledger modification operations:
compilation, projection rebuilds, and batch categorization.
Every mutation event records a sequence number (1-based, gapless), UTC timestamp,
operator session, action, staged count, rules applied, rules created, SHA-256 before/after
fingerprints, previous mutation hash, and canonical SHA-256 mutation hash.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Final

from ironledger.conventions import ConventionError, validate_utc_timestamp

__all__ = [
    "MutationVerificationError",
    "MutationEvent",
    "MutationVerificationResult",
    "GENESIS_MUTATION_PREV_HASH",
    "canonical_mutation_bytes",
    "compute_mutation_hash",
    "append_mutation_event",
    "load_mutation_events",
    "verify_mutation_chain",
]

GENESIS_MUTATION_PREV_HASH: Final[str] = "0" * 64


class MutationVerificationError(ValueError):
    """A mutation event chain failed verification due to gap, tamper, or reordering."""


@dataclass(frozen=True)
class MutationEvent:
    """Canonical mutation event envelope."""

    seq: int
    mutation_id: str
    ts_utc: str
    operator_session: str
    action: str
    staged_count: int
    rules_applied: int
    rules_created: int
    sha256_before: str
    sha256_after: str
    prev_mutation_hash: str = GENESIS_MUTATION_PREV_HASH
    mutation_hash: str = ""


@dataclass(frozen=True)
class MutationVerificationResult:
    """Summary of mutation chain verification."""

    is_valid: bool
    mutation_count: int
    head_hash: str | None


def canonical_mutation_bytes(event: MutationEvent | dict[str, Any]) -> bytes:
    """Return deterministic canonical UTF-8 bytes for the mutation event payload fields."""
    if isinstance(event, MutationEvent):
        data = asdict(event)
    elif isinstance(event, dict):
        data = dict(event)
    else:
        raise TypeError("event must be a MutationEvent instance or dict")

    payload = {
        "seq": data["seq"],
        "mutation_id": data["mutation_id"],
        "ts_utc": data["ts_utc"],
        "operator_session": data["operator_session"],
        "action": data["action"],
        "staged_count": data["staged_count"],
        "rules_applied": data["rules_applied"],
        "rules_created": data["rules_created"],
        "sha256_before": data["sha256_before"],
        "sha256_after": data["sha256_after"],
        "prev_mutation_hash": data["prev_mutation_hash"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded.encode("utf-8")


def compute_mutation_hash(event: MutationEvent | dict[str, Any]) -> str:
    """Compute the canonical SHA-256 digest of a mutation event payload."""
    return hashlib.sha256(canonical_mutation_bytes(event)).hexdigest()


def append_mutation_event(
    conn: sqlite3.Connection,
    *,
    operator_session: str,
    action: str,
    staged_count: int,
    rules_applied: int,
    rules_created: int,
    sha256_before: str,
    sha256_after: str,
    mutation_id: str | None = None,
    ts_utc: str | None = None,
) -> MutationEvent:
    """Allocate the next monotonic sequence, compute the hash chain, and record the mutation event."""
    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(ts_utc)

    if mutation_id is None:
        mutation_id = f"mut_{uuid.uuid4().hex[:12]}"

    if len(sha256_before) != 64:
        raise ValueError(f"sha256_before must be 64 characters, got {len(sha256_before)}")
    if len(sha256_after) != 64:
        raise ValueError(f"sha256_after must be 64 characters, got {len(sha256_after)}")

    cursor = conn.execute(
        "SELECT seq, mutation_hash FROM mutation_events ORDER BY seq DESC LIMIT 1"
    )
    last_row = cursor.fetchone()
    if last_row is None:
        next_seq = 1
        prev_hash = GENESIS_MUTATION_PREV_HASH
    else:
        last_seq, last_hash = last_row
        next_seq = last_seq + 1
        prev_hash = last_hash

    payload_event = MutationEvent(
        seq=next_seq,
        mutation_id=mutation_id,
        ts_utc=ts_utc,
        operator_session=operator_session,
        action=action,
        staged_count=staged_count,
        rules_applied=rules_applied,
        rules_created=rules_created,
        sha256_before=sha256_before,
        sha256_after=sha256_after,
        prev_mutation_hash=prev_hash,
    )
    mut_hash = compute_mutation_hash(payload_event)
    event = MutationEvent(
        seq=next_seq,
        mutation_id=mutation_id,
        ts_utc=ts_utc,
        operator_session=operator_session,
        action=action,
        staged_count=staged_count,
        rules_applied=rules_applied,
        rules_created=rules_created,
        sha256_before=sha256_before,
        sha256_after=sha256_after,
        prev_mutation_hash=prev_hash,
        mutation_hash=mut_hash,
    )

    conn.execute(
        "INSERT INTO mutation_events "
        "(seq, mutation_id, ts_utc, operator_session, action, staged_count, "
        " rules_applied, rules_created, sha256_before, sha256_after, prev_mutation_hash, mutation_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.seq,
            event.mutation_id,
            event.ts_utc,
            event.operator_session,
            event.action,
            event.staged_count,
            event.rules_applied,
            event.rules_created,
            event.sha256_before,
            event.sha256_after,
            event.prev_mutation_hash,
            event.mutation_hash,
        ),
    )
    return event


def load_mutation_events(conn: sqlite3.Connection) -> list[MutationEvent]:
    """Load all mutation events from the database ordered by sequence."""
    cursor = conn.execute(
        "SELECT seq, mutation_id, ts_utc, operator_session, action, staged_count, "
        "rules_applied, rules_created, sha256_before, sha256_after, prev_mutation_hash, mutation_hash "
        "FROM mutation_events ORDER BY seq ASC"
    )
    rows = cursor.fetchall()
    return [
        MutationEvent(
            seq=row[0],
            mutation_id=row[1],
            ts_utc=row[2],
            operator_session=row[3],
            action=row[4],
            staged_count=row[5],
            rules_applied=row[6],
            rules_created=row[7],
            sha256_before=row[8],
            sha256_after=row[9],
            prev_mutation_hash=row[10],
            mutation_hash=row[11],
        )
        for row in rows
    ]


def verify_mutation_chain(
    source: list[MutationEvent] | list[dict[str, Any]] | sqlite3.Connection,
) -> MutationVerificationResult:
    """Verify a mutation event chain from genesis through head hash.

    Validates:
    - Sequence is 1-based, strictly monotonic, and gapless.
    - Genesis event (seq=1) references GENESIS_MUTATION_PREV_HASH.
    - Each subsequent event (seq > 1) correctly references the previous event's hash.
    - Every event hash matches the canonical SHA-256 payload computation.
    - Every timestamp is valid UTC ISO-8601 with trailing Z.
    - Hash lengths and values comply with schema invariants.

    Raises :class:`MutationVerificationError` on any verification failure.
    """
    if isinstance(source, sqlite3.Connection):
        events = load_mutation_events(source)
    else:
        events = source

    if not events:
        return MutationVerificationResult(is_valid=True, mutation_count=0, head_hash=None)

    expected_prev_hash = GENESIS_MUTATION_PREV_HASH
    for index, item in enumerate(events):
        expected_seq = index + 1
        if isinstance(item, MutationEvent):
            event = item
        elif isinstance(item, dict):
            event = MutationEvent(**item)
        else:
            raise MutationVerificationError(f"invalid item type in mutation sequence: {type(item)}")

        if event.seq != expected_seq:
            raise MutationVerificationError(
                f"sequence gap or reordering at index {index}: expected seq {expected_seq}, found {event.seq}"
            )

        if event.prev_mutation_hash != expected_prev_hash:
            raise MutationVerificationError(
                f"broken hash link at seq {event.seq}: expected prev_mutation_hash {expected_prev_hash}, "
                f"found {event.prev_mutation_hash}"
            )

        computed_hash = compute_mutation_hash(event)
        if event.mutation_hash != computed_hash:
            raise MutationVerificationError(
                f"hash mismatch at seq {event.seq}: stored {event.mutation_hash}, computed {computed_hash}"
            )

        try:
            validate_utc_timestamp(event.ts_utc)
        except ConventionError as exc:
            raise MutationVerificationError(f"invalid timestamp at seq {event.seq}: {exc}") from exc

        expected_prev_hash = event.mutation_hash

    return MutationVerificationResult(
        is_valid=True,
        mutation_count=len(events),
        head_hash=events[-1].mutation_hash if isinstance(events[-1], MutationEvent) else events[-1]["mutation_hash"],
    )
