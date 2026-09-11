"""Data models and exceptions for Deterministic Audit Replay."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ReplayError(Exception):
    """Base exception for audit replay subsystem."""


class ReplayBoundaryError(ReplayError):
    """Raised when target replay sequence or timestamp exceeds available boundary."""


class MissingAnchorCommitmentError(ReplayError):
    """Raised when the external trust anchor is missing, unreadable, or corrupted."""


class AuditTamperDetectedError(ReplayError):
    """Raised when cryptographic signatures, Merkle hashes, or anchors fail verification."""


class PayloadValidationError(ReplayError):
    """Raised when a mutation payload violates JSON schema Draft-07 specification."""


class ManifestPromotionError(ReplayError):
    """Raised when atomic promotion of staged manifest directory fails."""


class ReconciliationFailedError(ReplayError):
    """Raised when startup reconciliation cannot safely resolve promotion state."""


class SecurityError(ReplayError):
    """Raised when path traversal, symlinks, or unauthorized escapes are detected."""


@dataclass(frozen=True)
class MutationPayload:
    seq: int
    mutation_id: str
    ledger_id: str
    payload_schema_version: int
    event_type: str
    payload_json: str
    payload_sha256: str
    projection_hash_before: str
    projection_hash_after: str
    created_at: str


@dataclass(frozen=True)
class TrustAnchor:
    anchor_version: int
    ledger_id: str
    seq: int
    mutation_id: str
    mutation_hash: str
    prev_mutation_hash: str
    manifest_hash: str
    projection_hash: str
    authority_signature: str
    anchored_at_utc: str


@dataclass
class ReplayVerificationReport:
    total_events_verified: int
    target_ledger_events_replayed: int
    interleaved_events_skipped: int
    final_sequence: int
    final_projection_hash: str
    final_manifest_hash: str
    verified_anchor: TrustAnchor | None = None
    replay_success: bool = True


@dataclass
class ReplayResult:
    report: ReplayVerificationReport
    projection_conn: sqlite3.Connection
    manifest_dir: Path
