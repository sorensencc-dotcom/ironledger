"""Cryptographic authority signatures and out-of-band trust anchors."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from ironledger.ledger.topology import validate_and_resolve_ledger_root
from ironledger.replay.models import (
    AuditTamperDetectedError,
    MissingAnchorCommitmentError,
    SecurityError,
    TrustAnchor,
)


def compute_anchor_signature_digest(
    seq: int,
    mutation_id: str,
    ledger_id: str,
    ts_utc: str,
    mutation_hash: str,
    prev_mutation_hash: str,
    manifest_hash: str,
    projection_hash: str,
) -> str:
    """Compute canonical SHA-256 digest string for signing and verifying audit authority signatures."""
    raw = f"{seq}:{mutation_id}:{ledger_id}:{ts_utc}:{mutation_hash}:{prev_mutation_hash}:{manifest_hash}:{projection_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sign_authority_payload(digest: str, authority_key: str | bytes) -> str:
    """Generate HMAC-SHA256 authority signature over the canonical digest."""
    key_bytes = authority_key.encode("utf-8") if isinstance(authority_key, str) else authority_key
    return hmac.new(key_bytes, digest.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_authority_signature(signature: str, digest: str, authority_key: str | bytes) -> bool:
    """Verify authority signature matches expected HMAC-SHA256 signature."""
    expected = sign_authority_payload(digest, authority_key)
    return hmac.compare_digest(signature, expected)


def get_anchor_path(beancount_root: Path | str, ledger_id: str) -> Path:
    """Get the external trust anchor file path for a ledger."""
    base = Path(beancount_root).resolve()
    anchor_dir = base / ".ironledger" / "anchors"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    return anchor_dir / f"{ledger_id}.anchor.json"


def read_trust_anchor(beancount_root: Path | str, ledger_id: str) -> TrustAnchor:
    """Read and parse external trust anchor for a ledger."""
    anchor_file = get_anchor_path(beancount_root, ledger_id)
    if not anchor_file.exists():
        raise MissingAnchorCommitmentError(f"Missing external trust anchor file for ledger '{ledger_id}': {anchor_file}")

    try:
        data = json.loads(anchor_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise MissingAnchorCommitmentError(f"Unreadable or corrupt trust anchor for ledger '{ledger_id}': {e}") from e

    required = [
        "anchor_version", "ledger_id", "seq", "mutation_id",
        "mutation_hash", "prev_mutation_hash", "manifest_hash",
        "projection_hash", "authority_signature", "anchored_at_utc"
    ]
    for key in required:
        if key not in data:
            raise MissingAnchorCommitmentError(f"Trust anchor missing required key '{key}'")

    return TrustAnchor(
        anchor_version=data["anchor_version"],
        ledger_id=data["ledger_id"],
        seq=data["seq"],
        mutation_id=data["mutation_id"],
        mutation_hash=data["mutation_hash"],
        prev_mutation_hash=data["prev_mutation_hash"],
        manifest_hash=data["manifest_hash"],
        projection_hash=data["projection_hash"],
        authority_signature=data["authority_signature"],
        anchored_at_utc=data["anchored_at_utc"],
    )


def write_trust_anchor(beancount_root: Path | str, anchor: TrustAnchor | dict[str, Any]) -> None:
    """Write trust anchor atomically via temp file replace."""
    if isinstance(anchor, TrustAnchor):
        data = {
            "anchor_version": anchor.anchor_version,
            "ledger_id": anchor.ledger_id,
            "seq": anchor.seq,
            "mutation_id": anchor.mutation_id,
            "mutation_hash": anchor.mutation_hash,
            "prev_mutation_hash": anchor.prev_mutation_hash,
            "manifest_hash": anchor.manifest_hash,
            "projection_hash": anchor.projection_hash,
            "authority_signature": anchor.authority_signature,
            "anchored_at_utc": anchor.anchored_at_utc,
        }
        ledger_id = anchor.ledger_id
    else:
        data = anchor
        ledger_id = data["ledger_id"]

    target_file = get_anchor_path(beancount_root, ledger_id)
    anchor_dir = target_file.parent
    temp_file = anchor_dir / f".a_{uuid4().hex}.tmp"
    temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temp_file, target_file)
