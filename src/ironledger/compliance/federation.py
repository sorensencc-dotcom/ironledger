"""Cross-cluster audit propagation and Merkle inclusion proof verification."""

from __future__ import annotations

import io
import json
import tarfile
from typing import Any, Final

from ironledger.compliance.bundle import ComplianceBundleError, MAX_ARCHIVE_BYTES, MAX_ARCHIVE_ENTRIES, _canonical_json_bytes
from ironledger.compliance.merkle import MerkleTree, verify_inclusion_proof


class CrossClusterProofError(ValueError):
    """Raised when cross-cluster proof export or verification fails."""


def export_cross_cluster_proof(
    archive_bytes: bytes,
    target_stream: str,
    target_seq: int,
) -> dict[str, Any]:
    """Extract a single event and compute its RFC 6962 inclusion proof from a sealed archive."""
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise CrossClusterProofError("Archive exceeds maximum allowed size")

    tar_buffer = io.BytesIO(archive_bytes)
    try:
        with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
            members = tar.getmembers()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise CrossClusterProofError("Archive exceeds max entry limit")

            manifest_member = tar.extractfile("manifest.json")
            if not manifest_member:
                raise CrossClusterProofError("manifest.json missing from archive")
            manifest = json.loads(manifest_member.read().decode("utf-8"))

            extracted_records: list[dict[str, Any]] = []
            for m in members:
                if m.name.startswith("streams/") and m.name.endswith(".jsonl") and m.isreg():
                    stream_file = tar.extractfile(m)
                    if stream_file:
                        for line in stream_file:
                            line = line.strip()
                            if line:
                                extracted_records.append(json.loads(line.decode("utf-8")))

            # Canonical sort order
            extracted_records.sort(
                key=lambda x: (x.get("stream", ""), x.get("seq", 0), x.get("timestamp_utc", x.get("ts_utc", "")))
            )

            canonical_leaves = [_canonical_json_bytes(rec) for rec in extracted_records]
            tree = MerkleTree(canonical_leaves)

            # Find matching record
            target_index = -1
            target_record = None
            for idx, rec in enumerate(extracted_records):
                if rec.get("stream") == target_stream and rec.get("seq") == target_seq:
                    target_index = idx
                    target_record = rec
                    break

            if target_index == -1 or target_record is None:
                raise CrossClusterProofError(
                    f"Target event not found in archive: stream={target_stream}, seq={target_seq}"
                )

            proof = tree.get_proof(target_index)

            return {
                "bundle_id": manifest["bundle_id"],
                "ledger_id": manifest["ledger_id"],
                "framework": manifest["framework"],
                "merkle_root_hex": tree.root_hex,
                "leaf_index": target_index,
                "target_stream": target_stream,
                "target_seq": target_seq,
                "leaf_payload": target_record,
                "proof": proof,
            }

    except Exception as exc:
        if isinstance(exc, CrossClusterProofError):
            raise
        raise CrossClusterProofError(f"Failed to export cross-cluster proof: {exc}") from exc


def verify_cross_cluster_proof(
    proof_bundle: dict[str, Any],
    expected_root_hex: str | None = None,
) -> bool:
    """Verify an isolated cross-cluster audit proof without loading the full archive or database."""
    for field in ("bundle_id", "merkle_root_hex", "leaf_payload", "proof"):
        if field not in proof_bundle:
            raise CrossClusterProofError(f"Malformed proof bundle: missing {field}")

    merkle_root = proof_bundle["merkle_root_hex"]
    if expected_root_hex and merkle_root.lower() != expected_root_hex.lower():
        return False

    leaf_bytes = _canonical_json_bytes(proof_bundle["leaf_payload"])
    proof = proof_bundle["proof"]

    return verify_inclusion_proof(leaf_bytes, proof, merkle_root)
