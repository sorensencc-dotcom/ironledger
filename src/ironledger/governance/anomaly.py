"""Pure rational anomaly and fraud detection engine for IronLedger.

Operates strictly via exact integer rational arithmetic (N/D) and
cross-multiplication on squared deviations. Zero floating-point division (/)
or float type conversions are permitted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Final

from ironledger.conventions import ConventionError, validate_utc_timestamp


DETECTOR_VERSION: Final[str] = "1.0.0"
VALID_RULE_TYPES: Final[tuple[str, ...]] = (
    "DUPLICATE_CHARGE",
    "VELOCITY_SPIKE",
    "RATIONAL_OUTLIER",
    "UNUSUAL_PAYEE",
)
VALID_SEVERITIES: Final[tuple[str, ...]] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
VALID_RESOLUTIONS: Final[tuple[str, ...]] = ("DISMISSED", "CONFIRMED_FRAUD", "RESOLVED_VALID")

MAX_INT64: Final[int] = 9223372036854775807
MIN_INT64: Final[int] = -9223372036854775808


class AnomalyEngineError(ValueError):
    """Raised when anomaly detection or resolution encounters invalid state."""


@dataclass(frozen=True)
class NormalizedTransaction:
    """Standardized representation of a transaction for anomaly evaluation."""

    id: str
    ledger_id: str
    timestamp_utc: str
    amount_cents: int  # Exact integer cents
    currency: str
    account_id: str
    payee: str
    description: str = ""


@dataclass(frozen=True)
class AnomalyFinding:
    """Detected anomaly finding."""

    flag_id: str
    ledger_id: str
    staged_transaction_id: str
    rule_type: str
    severity: str
    score_numerator: int
    score_denominator: int
    details: dict[str, Any]
    created_at_utc: str


def compute_flag_id(ledger_id: str, rule_type: str, tx_id: str, detector_version: str = DETECTOR_VERSION) -> str:
    """Generate a deterministic finding fingerprint."""
    raw = f"{ledger_id}:{rule_type}:{tx_id}:{detector_version}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _assert_int64(val: int, name: str) -> None:
    if val > MAX_INT64 or val < MIN_INT64:
        raise AnomalyEngineError(f"Integer overflow for {name}: {val} exceeds 64-bit bounds")


def detect_duplicate_charges(
    transactions: list[NormalizedTransaction],
    window_seconds: int = 86400,
) -> list[AnomalyFinding]:
    """Detect duplicate charges with identical account, currency, and amount within a time window."""
    findings: list[AnomalyFinding] = []
    sorted_txs = sorted(transactions, key=lambda t: (t.account_id, t.amount_cents, t.timestamp_utc))

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for i in range(len(sorted_txs)):
        tx1 = sorted_txs[i]
        # Parse ISO-8601 timestamp without floats
        ts1_sec = int(datetime.fromisoformat(tx1.timestamp_utc.replace("Z", "+00:00")).timestamp())

        for j in range(i + 1, len(sorted_txs)):
            tx2 = sorted_txs[j]
            if tx1.account_id != tx2.account_id or tx1.amount_cents != tx2.amount_cents or tx1.currency != tx2.currency:
                break

            ts2_sec = int(datetime.fromisoformat(tx2.timestamp_utc.replace("Z", "+00:00")).timestamp())
            diff_sec = ts2_sec - ts1_sec
            if diff_sec <= window_seconds:
                flag_id = compute_flag_id(tx2.ledger_id, "DUPLICATE_CHARGE", tx2.id)
                findings.append(
                    AnomalyFinding(
                        flag_id=flag_id,
                        ledger_id=tx2.ledger_id,
                        staged_transaction_id=tx2.id,
                        rule_type="DUPLICATE_CHARGE",
                        severity="HIGH",
                        score_numerator=1,
                        score_denominator=1,
                        details={
                            "matched_tx_id": tx1.id,
                            "amount_cents": tx2.amount_cents,
                            "account_id": tx2.account_id,
                            "delta_seconds": diff_sec,
                            "window_seconds": window_seconds,
                        },
                        created_at_utc=now_utc,
                    )
                )

    return findings


def detect_velocity_spikes(
    transactions: list[NormalizedTransaction],
    window_seconds: int = 3600,
    max_count: int = 5,
    max_volume_cents: int = 1000000,  # $10,000.00
) -> list[AnomalyFinding]:
    """Detect transaction velocity spikes within sliding time windows."""
    findings: list[AnomalyFinding] = []
    sorted_txs = sorted(transactions, key=lambda t: t.timestamp_utc)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for i, tx in enumerate(sorted_txs):
        ts_i = int(datetime.fromisoformat(tx.timestamp_utc.replace("Z", "+00:00")).timestamp())
        count = 0
        volume_cents = 0
        tx_ids: list[str] = []

        for j in range(i, -1, -1):
            prior_tx = sorted_txs[j]
            ts_j = int(datetime.fromisoformat(prior_tx.timestamp_utc.replace("Z", "+00:00")).timestamp())
            if (ts_i - ts_j) <= window_seconds:
                count += 1
                volume_cents += abs(prior_tx.amount_cents)
                tx_ids.append(prior_tx.id)
            else:
                break

        if count > max_count or volume_cents > max_volume_cents:
            severity = "CRITICAL" if (count > max_count * 2 or volume_cents > max_volume_cents * 2) else "HIGH"
            flag_id = compute_flag_id(tx.ledger_id, "VELOCITY_SPIKE", tx.id)
            findings.append(
                AnomalyFinding(
                    flag_id=flag_id,
                    ledger_id=tx.ledger_id,
                    staged_transaction_id=tx.id,
                    rule_type="VELOCITY_SPIKE",
                    severity=severity,
                    score_numerator=count,
                    score_denominator=max_count,
                    details={
                        "window_count": count,
                        "max_count": max_count,
                        "window_volume_cents": volume_cents,
                        "max_volume_cents": max_volume_cents,
                        "window_seconds": window_seconds,
                        "window_tx_ids": tx_ids,
                    },
                    created_at_utc=now_utc,
                )
            )

    return findings


def detect_rational_outliers(
    transactions: list[NormalizedTransaction],
    k_numerator: int = 3,
    k_denominator: int = 1,
) -> list[AnomalyFinding]:
    """Detect statistical outliers using pure rational arithmetic on squared deviations.
    
    Formula:
    Sample size N = len(transactions)
    Sum S = sum(amount_cents)
    D = sum((N * x_i - S)^2)
    For N > 1 and D > 0:
    Outlier condition: (N * x - S)^2 * (N - 1) * k_den^2 > k_num^2 * D
    """
    if k_denominator <= 0 or k_numerator <= 0:
        raise AnomalyEngineError("Threshold k must be positive rational (k_num > 0, k_den > 0)")

    n = len(transactions)
    if n <= 1:
        return []

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    findings: list[AnomalyFinding] = []

    # Amounts
    amounts = [abs(t.amount_cents) for t in transactions]
    s = sum(amounts)
    _assert_int64(s, "sum_of_amounts")

    # Compute D = sum((N * x_i - S)^2)
    d = 0
    for x in amounts:
        diff = n * x - s
        d += diff * diff

    if d == 0:
        # Zero variance: all values identical
        return []

    _assert_int64(d, "squared_deviations_sum")

    k_num_sq = k_numerator * k_numerator
    k_den_sq = k_denominator * k_denominator
    rhs = k_num_sq * d

    for tx in transactions:
        x = abs(tx.amount_cents)
        diff = n * x - s
        diff_sq = diff * diff
        lhs = diff_sq * (n - 1) * k_den_sq

        if lhs > rhs:
            flag_id = compute_flag_id(tx.ledger_id, "RATIONAL_OUTLIER", tx.id)
            score_num = diff_sq * (n - 1)
            score_den = d if d != 0 else 1
            # Bound persisted score to 64-bit integer
            if score_num > MAX_INT64 or score_den > MAX_INT64:
                # Scale down by common integer reduction if needed
                score_num = min(score_num, MAX_INT64)
                score_den = max(1, min(score_den, MAX_INT64))

            findings.append(
                AnomalyFinding(
                    flag_id=flag_id,
                    ledger_id=tx.ledger_id,
                    staged_transaction_id=tx.id,
                    rule_type="RATIONAL_OUTLIER",
                    severity="HIGH" if lhs > (rhs * 4) else "MEDIUM",
                    score_numerator=score_num,
                    score_denominator=score_den,
                    details={
                        "amount_cents": tx.amount_cents,
                        "mean_cents_num": s,
                        "mean_cents_den": n,
                        "k_threshold": f"{k_numerator}/{k_denominator}",
                        "sample_size": n,
                    },
                    created_at_utc=now_utc,
                )
            )

    return findings


def detect_unusual_payees(
    transactions: list[NormalizedTransaction],
    history_transactions: list[NormalizedTransaction] | None = None,
    min_history_size: int = 10,
    max_payee_frequency_num: int = 1,
    max_payee_frequency_den: int = 20,  # <= 5% frequency
) -> list[AnomalyFinding]:
    """Flag payees with rare or single-occurrence frequency in transaction history."""
    corpus = (history_transactions or []) + transactions
    if len(corpus) < min_history_size:
        return []

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    findings: list[AnomalyFinding] = []

    # Frequency count per payee
    counts: dict[str, int] = {}
    for t in corpus:
        p = (t.payee or "").strip().lower()
        if p:
            counts[p] = counts.get(p, 0) + 1

    total = len(corpus)
    threshold_lhs = max_payee_frequency_num * total

    for tx in transactions:
        p = (tx.payee or "").strip().lower()
        if not p:
            continue

        c = counts.get(p, 0)
        # Check if count / total <= num / den <=> count * den <= num * total
        if (c * max_payee_frequency_den) <= threshold_lhs:
            flag_id = compute_flag_id(tx.ledger_id, "UNUSUAL_PAYEE", tx.id)
            findings.append(
                AnomalyFinding(
                    flag_id=flag_id,
                    ledger_id=tx.ledger_id,
                    staged_transaction_id=tx.id,
                    rule_type="UNUSUAL_PAYEE",
                    severity="LOW" if c > 1 else "MEDIUM",
                    score_numerator=c,
                    score_denominator=total,
                    details={
                        "payee": tx.payee,
                        "payee_count": c,
                        "total_corpus_size": total,
                        "threshold": f"{max_payee_frequency_num}/{max_payee_frequency_den}",
                    },
                    created_at_utc=now_utc,
                )
            )

    return findings


def scan_and_persist_anomalies(
    conn: sqlite3.Connection,
    ledger_id: str,
    transactions: list[NormalizedTransaction],
    rules: tuple[str, ...] = VALID_RULE_TYPES,
) -> list[AnomalyFinding]:
    """Execute anomaly scanners and persist detected flags to anomaly_flags table."""
    all_findings: list[AnomalyFinding] = []

    if "DUPLICATE_CHARGE" in rules:
        all_findings.extend(detect_duplicate_charges(transactions))
    if "VELOCITY_SPIKE" in rules:
        all_findings.extend(detect_velocity_spikes(transactions))
    if "RATIONAL_OUTLIER" in rules:
        all_findings.extend(detect_rational_outliers(transactions))
    if "UNUSUAL_PAYEE" in rules:
        all_findings.extend(detect_unusual_payees(transactions))

    cursor = conn.cursor()
    for f in all_findings:
        _assert_int64(f.score_numerator, "score_numerator")
        _assert_int64(f.score_denominator, "score_denominator")
        cursor.execute(
            """
            INSERT INTO anomaly_flags (
                ledger_id, flag_id, staged_transaction_id, rule_type, severity,
                score_numerator, score_denominator, details_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ledger_id, flag_id) DO UPDATE SET
                details_json = excluded.details_json,
                severity = excluded.severity
            WHERE resolution_status IS NULL
            """,
            (
                f.ledger_id,
                f.flag_id,
                f.staged_transaction_id,
                f.rule_type,
                f.severity,
                f.score_numerator,
                f.score_denominator,
                json.dumps(f.details, sort_keys=True),
                f.created_at_utc,
            ),
        )

    return all_findings


def resolve_anomaly_flag(
    conn: sqlite3.Connection,
    ledger_id: str,
    flag_id: str,
    resolution_status: str,
    actor: str,
    reason: str = "",
) -> bool:
    """Atomically resolve an anomaly flag and append a governance audit event."""
    if resolution_status not in VALID_RESOLUTIONS:
        raise AnomalyEngineError(
            f"Invalid resolution_status: {resolution_status}. Must be one of {VALID_RESOLUTIONS}"
        )

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor = conn.cursor()

    # Read current state
    cursor.execute(
        """
        SELECT rule_type, severity, details_json, resolution_status
        FROM anomaly_flags
        WHERE ledger_id = ? AND flag_id = ?
        """,
        (ledger_id, flag_id),
    )
    row = cursor.fetchone()
    if not row:
        raise AnomalyEngineError(f"Anomaly flag not found: {flag_id} in ledger {ledger_id}")

    if row[3] is not None:
        raise AnomalyEngineError(f"Anomaly flag {flag_id} is already resolved as {row[3]}")

    before_state = {
        "rule_type": row[0],
        "severity": row[1],
        "resolution_status": row[3],
    }
    after_state = {
        "rule_type": row[0],
        "severity": row[1],
        "resolution_status": resolution_status,
        "resolved_at_utc": now_utc,
        "resolver": actor,
        "reason": reason,
    }

    # Compare-and-set update
    cursor.execute(
        """
        UPDATE anomaly_flags
        SET resolution_status = ?, resolved_at_utc = ?
        WHERE ledger_id = ? AND flag_id = ? AND resolution_status IS NULL
        """,
        (resolution_status, now_utc, ledger_id, flag_id),
    )

    if cursor.rowcount == 0:
        return False

    # Emit governance audit event
    envelope_data = {
        "ledger_id": ledger_id,
        "actor": actor,
        "action": "RESOLVE_ANOMALY_FLAG",
        "target": f"anomaly_flag:{flag_id}",
        "before_state": before_state,
        "after_state": after_state,
        "timestamp_utc": now_utc,
    }
    envelope_bytes = json.dumps(envelope_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    envelope_hash = hashlib.sha256(envelope_bytes).hexdigest()

    cursor.execute(
        """
        INSERT INTO governance_audit_events (
            ledger_id, actor, action, target, before_state_json, after_state_json,
            envelope_hash, timestamp_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ledger_id,
            actor,
            "RESOLVE_ANOMALY_FLAG",
            f"anomaly_flag:{flag_id}",
            json.dumps(before_state, sort_keys=True),
            json.dumps(after_state, sort_keys=True),
            envelope_hash,
            now_utc,
        ),
    )

    return True
