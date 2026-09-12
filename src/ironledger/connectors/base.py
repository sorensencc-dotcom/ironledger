"""Base connector abstract class."""

from __future__ import annotations

import abc
import datetime
import json
import sqlite3
import uuid
from typing import Any

from ironledger.connectors.circuit_breaker import CircuitBreaker
from ironledger.connectors.models import (
    ConnectorError,
    ConnectorProvider,
    ConnectorRecord,
    RateLimitExceededError,
    SyncResult,
    SyncStatus,
)
from ironledger.connectors.rate_limiter import TokenBucketRateLimiter


class BaseConnector(abc.ABC):
    """Abstract base class for financial institution connectors."""

    def __init__(
        self,
        provider: ConnectorProvider,
        rate_limiter: TokenBucketRateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self.provider = provider
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(
            rate_limit_rpm=provider.rate_limit_rpm,
            burst_capacity=provider.burst_capacity,
        )
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    @abc.abstractmethod
    def parse_payload(self, raw_data: Any) -> list[ConnectorRecord]:
        """Parses raw provider response data into canonical ConnectorRecord list."""

    @abc.abstractmethod
    def fetch_transactions(
        self,
        credentials: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> list[ConnectorRecord]:
        """Fetches transactions from upstream institution API."""

    def sync(
        self,
        conn: sqlite3.Connection,
        ledger_id: str,
        credentials: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> SyncResult:
        """Executes a governed synchronization run with rate limiting and circuit breaking."""
        run_id = f"sync_{uuid.uuid4().hex[:12]}"
        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Assert Rate Limiter
        if not self.rate_limiter.acquire(1):
            wait_ms = self.rate_limiter.get_wait_time_ms(1)
            result = SyncResult(
                run_id=run_id,
                ledger_id=ledger_id,
                provider_id=self.provider.provider_id,
                status=SyncStatus.FAILED,
                error_code="RATE_LIMITED",
                error_details=f"Rate limit exceeded; retry after {wait_ms}ms",
                started_at_utc=now_utc,
                completed_at_utc=now_utc,
            )
            self._record_sync_run(conn, result)
            raise RateLimitExceededError(result.error_details)

        # 2. Check Circuit Breaker & Execute Fetch
        try:
            records = self.circuit_breaker.execute(
                self.fetch_transactions,
                credentials=credentials,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            completed_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            status = SyncStatus.CIRCUIT_BROKEN if self.circuit_breaker.state.value == "OPEN" else SyncStatus.FAILED
            result = SyncResult(
                run_id=run_id,
                ledger_id=ledger_id,
                provider_id=self.provider.provider_id,
                status=status,
                error_code=exc.__class__.__name__,
                error_details=str(exc),
                started_at_utc=now_utc,
                completed_at_utc=completed_utc,
            )
            self._record_sync_run(conn, result)
            raise

        # 3. Stage Records in SQLite
        staged_count = self._stage_records(conn, ledger_id, records)
        completed_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        result = SyncResult(
            run_id=run_id,
            ledger_id=ledger_id,
            provider_id=self.provider.provider_id,
            status=SyncStatus.SUCCESS,
            records_fetched=len(records),
            records_staged=staged_count,
            started_at_utc=now_utc,
            completed_at_utc=completed_utc,
        )
        self._record_sync_run(conn, result)
        return result

    def _stage_records(
        self,
        conn: sqlite3.Connection,
        ledger_id: str,
        records: list[ConnectorRecord],
    ) -> int:
        count = 0
        for rec in records:
            payload = {
                "record_id": rec.record_id,
                "account_id": rec.account_id,
                "date": rec.posted_date,
                "amount_minor": rec.amount_minor,
                "currency": rec.currency,
                "payee": rec.payee,
                "memo": rec.memo,
                "provider_id": self.provider.provider_id,
            }
            conn.execute(
                """
                INSERT INTO tenant_staging_operations (ledger_id, operation_json, status, created_at)
                VALUES (?, ?, 'pending', datetime('now'))
                """,
                (ledger_id, json.dumps(payload)),
            )
            count += 1
        return count

    def _record_sync_run(self, conn: sqlite3.Connection, res: SyncResult) -> None:
        conn.execute(
            """
            INSERT INTO connector_sync_runs (
                ledger_id, run_id, provider_id, status, records_fetched, records_staged,
                error_code, error_details, started_at_utc, completed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                res.ledger_id,
                res.run_id,
                res.provider_id,
                res.status.value,
                res.records_fetched,
                res.records_staged,
                res.error_code,
                res.error_details,
                res.started_at_utc,
                res.completed_at_utc,
            ),
        )