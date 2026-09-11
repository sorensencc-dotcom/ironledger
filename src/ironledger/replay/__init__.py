"""Deterministic Audit Replay Subsystem."""

from __future__ import annotations

from ironledger.replay.anchors import (
    compute_anchor_signature_digest,
    get_anchor_path,
    read_trust_anchor,
    sign_authority_payload,
    verify_authority_signature,
    write_trust_anchor,
)
from ironledger.replay.engine import (
    apply_mutation_and_append,
    reconcile_manifest_on_startup,
    replay_audit_stream,
)
from ironledger.replay.models import (
    AuditTamperDetectedError,
    ManifestPromotionError,
    MissingAnchorCommitmentError,
    MutationPayload,
    PayloadValidationError,
    ReconciliationFailedError,
    ReplayBoundaryError,
    ReplayError,
    ReplayResult,
    ReplayVerificationReport,
    SecurityError,
    TrustAnchor,
)
from ironledger.replay.schemas import validate_payload_schema
from ironledger.replay.snapshot import (
    GENESIS_PROJECTION_HASH,
    compute_projection_hash,
    dispatch_event_mutation,
)

__all__ = [
    "ReplayError",
    "ReplayBoundaryError",
    "MissingAnchorCommitmentError",
    "AuditTamperDetectedError",
    "PayloadValidationError",
    "ManifestPromotionError",
    "ReconciliationFailedError",
    "SecurityError",
    "MutationPayload",
    "TrustAnchor",
    "ReplayVerificationReport",
    "ReplayResult",
    "validate_payload_schema",
    "compute_anchor_signature_digest",
    "sign_authority_payload",
    "verify_authority_signature",
    "get_anchor_path",
    "read_trust_anchor",
    "write_trust_anchor",
    "GENESIS_PROJECTION_HASH",
    "compute_projection_hash",
    "dispatch_event_mutation",
    "apply_mutation_and_append",
    "reconcile_manifest_on_startup",
    "replay_audit_stream",
]
