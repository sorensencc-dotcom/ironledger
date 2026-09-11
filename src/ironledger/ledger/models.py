"""Data models for Multi-Ledger Topology, Staging, and Consolidated Reporting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

LEDGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
CURRENCY_PATTERN = re.compile(r"^[A-Z0-9_.-]{1,12}\Z")


@dataclass(frozen=True)
class LedgerTopology:
    ledger_id: str
    name: str
    root_account: str = "Assets"
    base_currency: str = "USD"
    storage_root: str = ""
    is_active: bool = True
    created_at_utc: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ledger_id, str) or not LEDGER_ID_PATTERN.match(self.ledger_id):
            raise ValueError(f"Invalid ledger_id: {self.ledger_id!r}")
        if not isinstance(self.name, str) or not (1 <= len(self.name) <= 128):
            raise ValueError(f"Invalid name length: {len(self.name)}")
        if not isinstance(self.base_currency, str) or not CURRENCY_PATTERN.match(self.base_currency):
            raise ValueError(f"Invalid base_currency: {self.base_currency!r}")


@dataclass(frozen=True)
class TenantStagingQueue:
    ledger_id: str
    pending_count: int


@dataclass(frozen=True)
class LedgerAccountMapping:
    ledger_id: str
    id: int
    parent_id: int | None
    name: str
    type: str


@dataclass(frozen=True)
class EntityBalance:
    ledger_id: str
    name: str
    account: str
    amount_minor: int
    currency: str
    scale: int
    converted_minor: int
    target_currency: str


@dataclass
class ConsolidatedBalanceSheet:
    base_currency: str
    as_of_date: str
    total_minor: int
    scale: int = 2
    entities: list[LedgerTopology] = field(default_factory=list)
    balances: list[EntityBalance] = field(default_factory=list)
