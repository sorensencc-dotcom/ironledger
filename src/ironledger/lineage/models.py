"""Data models and exceptions for ledger lineage and provenance DAG."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

NODE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}\Z")
LEDGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")

NodeType = Literal[
    "EVIDENCE_BLOB",
    "SOURCE_RECORD",
    "STAGED_TX",
    "POSTING",
    "PRICE_DIRECTIVE",
    "EVIDENCE",
]

RelationshipType = Literal[
    "EXTRACTED_FROM",
    "STAGED_FROM",
    "COMPILED_FROM",
    "DERIVED_FROM",
    "COMPILED_INTO",
    "VALUED_BY",
]


class LineageError(Exception):
    """Base exception for lineage subsystem errors."""


class LineageNodeNotFoundError(LineageError):
    """Raised when a referenced lineage node does not exist."""


class LineageCycleError(LineageError):
    """Raised when an edge would create a cycle or self-loop in the DAG."""


@dataclass(frozen=True)
class LineageNode:
    node_id: str
    node_type: NodeType
    entity_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)
    ledger_id: str = "default"
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not NODE_ID_PATTERN.match(self.node_id):
            raise ValueError(f"Invalid node_id: {self.node_id!r}")
        if not isinstance(self.ledger_id, str) or not LEDGER_ID_PATTERN.match(self.ledger_id):
            raise ValueError(f"Invalid ledger_id: {self.ledger_id!r}")
        if not isinstance(self.entity_ref, str) or not (1 <= len(self.entity_ref) <= 128):
            raise ValueError(f"Invalid entity_ref length: {len(self.entity_ref)}")
        if self.node_type not in (
            "EVIDENCE_BLOB",
            "SOURCE_RECORD",
            "STAGED_TX",
            "POSTING",
            "PRICE_DIRECTIVE",
            "EVIDENCE",
        ):
            raise ValueError(f"Invalid node_type: {self.node_type!r}")


@dataclass(frozen=True)
class LineageEdge:
    ledger_id: str
    source_node_id: str
    target_node_id: str
    relationship: RelationshipType
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ledger_id, str) or not LEDGER_ID_PATTERN.match(self.ledger_id):
            raise ValueError(f"Invalid ledger_id: {self.ledger_id!r}")
        if not isinstance(self.source_node_id, str) or not NODE_ID_PATTERN.match(self.source_node_id):
            raise ValueError(f"Invalid source_node_id: {self.source_node_id!r}")
        if not isinstance(self.target_node_id, str) or not NODE_ID_PATTERN.match(self.target_node_id):
            raise ValueError(f"Invalid target_node_id: {self.target_node_id!r}")
        if self.source_node_id == self.target_node_id:
            raise LineageCycleError(f"Self-edges are forbidden: {self.source_node_id} -> {self.target_node_id}")
        if self.relationship not in (
            "EXTRACTED_FROM",
            "STAGED_FROM",
            "COMPILED_FROM",
            "DERIVED_FROM",
            "COMPILED_INTO",
            "VALUED_BY",
        ):
            raise ValueError(f"Invalid relationship: {self.relationship!r}")


@dataclass
class LineageGraph:
    nodes: list[LineageNode] = field(default_factory=list)
    edges: list[LineageEdge] = field(default_factory=list)
