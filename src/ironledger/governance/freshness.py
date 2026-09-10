"""Projection freshness and SLA monitoring engine.

Reconciles SLA monitoring requirements (IL-GOV-SPEC-007):
1. Unidirectional Latency:
   delta_t = max(0.0, current_utc - built_at_utc)
   Clock rollback or future timestamps are gracefully clamped to 0.0s.
2. Hash Divergence Detection:
   Live canonical manifest SHA-256 of the ledger directory is compared
   against the projection database's recorded source digest.
3. SLA Freshness Tiers:
   - FRESH: delta_t < 5.0s AND source_hash_match is True.
   - STALE: 5.0s <= delta_t <= 30.0s AND source_hash_match is True.
   - CRITICAL: delta_t > 30.0s OR source_hash_match is False (hash divergence
     independently forces CRITICAL).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Final

from ironledger.governance.mutations import compute_canonical_ledger_manifest_hash

__all__ = [
    "FreshnessTier",
    "ProjectionFreshnessResult",
    "FRESH_THRESHOLD_SECONDS",
    "STALE_THRESHOLD_SECONDS",
    "evaluate_projection_freshness",
    "check_projection_db_freshness",
]

FRESH_THRESHOLD_SECONDS: Final[float] = 5.0
STALE_THRESHOLD_SECONDS: Final[float] = 30.0


class FreshnessTier(str, Enum):
    """SLA freshness tiers for projection databases."""

    FRESH = "fresh"
    STALE = "stale"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ProjectionFreshnessResult:
    """Evaluated freshness and SLA compliance result."""

    status: FreshnessTier
    latency_seconds: float
    source_hash_match: bool
    ledger_source_sha256: str
    projection_source_sha256: str
    built_at_utc: str


def _parse_iso_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp string into a timezone-aware datetime."""
    normalized = ts.strip()
    if normalized.endswith("Z") or normalized.endswith("z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def evaluate_projection_freshness(
    ledger_source_sha256: str,
    projection_source_sha256: str,
    built_at_utc: str,
    now_utc: str | None = None,
) -> ProjectionFreshnessResult:
    """Evaluate projection freshness SLA status and latency against current time.

    Args:
        ledger_source_sha256: Live canonical SHA-256 digest of ledger directory manifest.
        projection_source_sha256: Source SHA-256 digest recorded in projection metadata.
        built_at_utc: ISO-8601 UTC timestamp when projection was built.
        now_utc: Optional ISO-8601 UTC timestamp to evaluate against (defaults to now).

    Returns:
        ProjectionFreshnessResult containing status tier, latency, and hash match flags.
    """
    built_dt = _parse_iso_utc(built_at_utc)
    if now_utc is None:
        now_dt = datetime.now(timezone.utc)
    else:
        now_dt = _parse_iso_utc(now_utc)

    delta_t = (now_dt - built_dt).total_seconds()
    latency_seconds = max(0.0, round(delta_t, 6))

    source_hash_match = bool(
        ledger_source_sha256
        and projection_source_sha256
        and (ledger_source_sha256.strip().lower() == projection_source_sha256.strip().lower())
    )

    if not source_hash_match:
        status = FreshnessTier.CRITICAL
    elif latency_seconds < FRESH_THRESHOLD_SECONDS:
        status = FreshnessTier.FRESH
    elif latency_seconds <= STALE_THRESHOLD_SECONDS:
        status = FreshnessTier.STALE
    else:
        status = FreshnessTier.CRITICAL

    return ProjectionFreshnessResult(
        status=status,
        latency_seconds=latency_seconds,
        source_hash_match=source_hash_match,
        ledger_source_sha256=ledger_source_sha256,
        projection_source_sha256=projection_source_sha256,
        built_at_utc=built_at_utc,
    )


def check_projection_db_freshness(
    projection_db_path: Path | str,
    ledger_dir: Path | str,
    now_utc: str | None = None,
) -> ProjectionFreshnessResult:
    """Inspect a SQLite projection database and evaluate freshness against live ledger.

    Queries ``projection_metadata`` (or ``projection_meta``) table for ``built_at_utc``
    and source hash, computes the live canonical ledger manifest hash, and evaluates SLA.

    Args:
        projection_db_path: Path to the SQLite projection database file.
        ledger_dir: Path to the root ledger directory containing beancount files.
        now_utc: Optional ISO-8601 UTC timestamp string for deterministic evaluation.

    Returns:
        ProjectionFreshnessResult.

    Raises:
        FileNotFoundError: If projection_db_path or ledger_dir does not exist.
        sqlite3.OperationalError: If metadata table or expected columns are absent.
    """
    db_path = Path(projection_db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Projection database not found: {db_path}")

    ledger_path = Path(ledger_dir)
    if not ledger_path.exists():
        raise FileNotFoundError(f"Ledger directory not found: {ledger_path}")

    live_ledger_sha256 = compute_canonical_ledger_manifest_hash(ledger_path)

    with sqlite3.connect(str(db_path)) as conn:
        # Locate projection metadata table
        table_name: str | None = None
        for candidate in ("projection_metadata", "projection_meta"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
                (candidate,),
            ).fetchone()
            if row:
                table_name = candidate
                break

        if table_name is None:
            raise sqlite3.OperationalError(
                f"No projection metadata table ('projection_metadata' or 'projection_meta') found in {db_path}"
            )

        cols_info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        col_names = [col[1] for col in cols_info]

        # Resolve source hash column
        hash_col: str | None = None
        for candidate_col in ("source_sha256", "ledger_source_sha256", "ledger_output_hash", "source_hash"):
            if candidate_col in col_names:
                hash_col = candidate_col
                break

        if hash_col is None:
            raise sqlite3.OperationalError(
                f"Metadata table '{table_name}' has no recognized hash column (expected one of: source_sha256, ledger_source_sha256, ledger_output_hash)"
            )

        # Resolve built_at column
        built_col: str | None = None
        for candidate_col in ("built_at_utc", "created_ts_utc", "built_at"):
            if candidate_col in col_names:
                built_col = candidate_col
                break

        if built_col is None:
            raise sqlite3.OperationalError(
                f"Metadata table '{table_name}' has no recognized timestamp column (expected built_at_utc)"
            )

        meta_row = conn.execute(f"SELECT {hash_col}, {built_col} FROM {table_name} LIMIT 1").fetchone()
        if meta_row is None:
            raise sqlite3.OperationalError(f"Projection metadata table '{table_name}' is empty")

        proj_source_sha256 = str(meta_row[0])
        built_at_utc = str(meta_row[1])

    return evaluate_projection_freshness(
        ledger_source_sha256=live_ledger_sha256,
        projection_source_sha256=proj_source_sha256,
        built_at_utc=built_at_utc,
        now_utc=now_utc,
    )
