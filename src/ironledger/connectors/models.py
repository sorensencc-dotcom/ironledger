"""Domain models, enums, and exceptions for financial data connectors."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProtocolType(str, Enum):
    PLAID = "PLAID"
    SIMPLEFIN = "SIMPLEFIN"
    OFX = "OFX"
    REST_JSON = "REST_JSON"


class SyncStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CIRCUIT_BROKEN = "CIRCUIT_BROKEN"


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    HALF_OPEN = "HALF_OPEN"
    OPEN = "OPEN"


class ConnectorError(Exception):
    """Base exception for connector operations."""


class RateLimitExceededError(ConnectorError):
    """Raised when request rate exceeds configured provider limits."""


class CircuitBreakerOpenError(ConnectorError):
    """Raised when the circuit breaker is OPEN, fast-failing outbound requests."""


class ProviderUnavailableError(ConnectorError):
    """Raised when provider endpoint returns 5xx or connection times out."""


class AuthenticationError(ConnectorError):
    """Raised when provider credentials or access tokens fail authentication."""


class PayloadParseError(ConnectorError):
    """Raised when raw banking payload fails schema parsing."""


@dataclass(frozen=True)
class ConnectorProvider:
    provider_id: str
    name: str
    protocol_type: ProtocolType
    base_url: str
    is_active: bool = True
    rate_limit_rpm: int = 60
    burst_capacity: int = 10
    config: dict[str, Any] = field(default_factory=dict)
    created_at_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


@dataclass(frozen=True)
class ConnectorRecord:
    record_id: str
    account_id: str
    posted_date: str  # YYYY-MM-DD
    amount_minor: int  # integer minor units
    currency: str
    payee: str
    memo: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SyncResult:
    run_id: str
    ledger_id: str
    provider_id: str
    status: SyncStatus
    records_fetched: int = 0
    records_staged: int = 0
    error_code: str | None = None
    error_details: str | None = None
    started_at_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    completed_at_utc: str | None = None