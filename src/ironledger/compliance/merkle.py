"""RFC 6962 deterministic binary Merkle tree for compliance audit bundles.

Provides domain-separated leaf and internal node hashing to prevent
second-preimage attacks:
- Leaf hash: SHA-256(0x00 || payload_bytes)
- Internal node hash: SHA-256(0x01 || left_hash_bytes || right_hash_bytes)
- Unpaired odd leaf: Promoted directly to the next level.
- Empty tree root: SHA-256(b"")
"""

from __future__ import annotations

import hashlib
from typing import Sequence


EMPTY_TREE_ROOT: str = hashlib.sha256(b"").hexdigest()


def hash_leaf(payload: bytes) -> bytes:
    """Compute RFC 6962 leaf hash: SHA-256(0x00 || payload)."""
    return hashlib.sha256(b"\x00" + payload).digest()


def hash_internal(left: bytes, right: bytes) -> bytes:
    """Compute RFC 6962 internal node hash: SHA-256(0x01 || left || right)."""
    return hashlib.sha256(b"\x01" + left + right).digest()


class MerkleTree:
    """Deterministic binary Merkle tree over canonical event byte payloads."""

    def __init__(self, leaves: Sequence[bytes] | None = None) -> None:
        self._raw_leaves: list[bytes] = list(leaves) if leaves else []
        self._leaf_hashes: list[bytes] = [hash_leaf(leaf) for leaf in self._raw_leaves]
        self._root_bytes: bytes = self._compute_root(self._leaf_hashes)

    @property
    def root_hex(self) -> str:
        """Return 64-character lowercase hex string of the Merkle root."""
        return self._root_bytes.hex()

    @property
    def leaf_count(self) -> int:
        """Return total number of leaves in the tree."""
        return len(self._raw_leaves)

    @staticmethod
    def _compute_root(hashes: Sequence[bytes]) -> bytes:
        if not hashes:
            return bytes.fromhex(EMPTY_TREE_ROOT)
        if len(hashes) == 1:
            return hashes[0]

        current_level = list(hashes)
        while len(current_level) > 1:
            next_level: list[bytes] = []
            i = 0
            while i < len(current_level):
                if i + 1 < len(current_level):
                    parent = hash_internal(current_level[i], current_level[i + 1])
                    next_level.append(parent)
                    i += 2
                else:
                    # Unpaired odd leaf: promoted directly to next level
                    next_level.append(current_level[i])
                    i += 1
            current_level = next_level

        return current_level[0]

    def get_proof(self, index: int) -> list[tuple[str, str]]:
        """Generate an audit inclusion proof for leaf at given 0-based index.
        
        Returns a list of (direction, sibling_hash_hex) tuples where direction
        is 'left' if the sibling is to the left, or 'right' if to the right.
        """
        if index < 0 or index >= len(self._leaf_hashes):
            raise IndexError("Leaf index out of bounds")

        proof: list[tuple[str, str]] = []
        current_level = list(self._leaf_hashes)
        target_idx = index

        while len(current_level) > 1:
            next_level: list[bytes] = []
            i = 0
            while i < len(current_level):
                if i + 1 < len(current_level):
                    left = current_level[i]
                    right = current_level[i + 1]
                    if i == target_idx:
                        proof.append(("right", right.hex()))
                    elif i + 1 == target_idx:
                        proof.append(("left", left.hex()))
                    next_level.append(hash_internal(left, right))
                    i += 2
                else:
                    if i == target_idx:
                        # Odd leaf promoted without sibling
                        pass
                    next_level.append(current_level[i])
                    i += 1
            target_idx = target_idx // 2
            current_level = next_level

        return proof


def verify_inclusion_proof(leaf_payload: bytes, proof: Sequence[tuple[str, str]], expected_root_hex: str) -> bool:
    """Verify an RFC 6962 Merkle inclusion proof."""
    current = hash_leaf(leaf_payload)
    for direction, sibling_hex in proof:
        sibling = bytes.fromhex(sibling_hex)
        if direction == "left":
            current = hash_internal(sibling, current)
        elif direction == "right":
            current = hash_internal(current, sibling)
        else:
            raise ValueError(f"Invalid proof direction: {direction}")

    return current.hex() == expected_root_hex
