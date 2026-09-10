"""Hit Confidence Trend (HCT) rule drift tracker and health classification.

Reconciles IL-GOV-SPEC-006 and IL-GOV-DRIFT-001:
1. Override Rate: O_R = N_overrides / N_total
2. Hit Confidence Trend: HCT_R = max(0.0, 1.0 - (O_R * 1.5) - lambda * delta_t_days)
   where lambda = 0.005 day^-1 decay factor.

Health tiers:
- EVALUATING: hits < 5 (provisional flag is True, tier is EVALUATING, HCT = 1.0 or calculated)
- HEALTHY: HCT >= 0.80 and O_R < 0.05 (for hits >= 5)
- WARNING: 0.50 <= HCT < 0.80 or 0.05 <= O_R < 0.15
- CRITICAL: HCT < 0.50 or O_R >= 0.15
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from ironledger.ingest.identity import canonical_payee

__all__ = [
    "RuleHealthTier",
    "RuleDriftMetrics",
    "calculate_hct",
    "evaluate_rule_drift",
    "audit_all_rules_drift",
    "DEFAULT_DECAY_LAMBDA",
    "MIN_HITS_FOR_EVALUATION",
    "OVERRIDE_WEIGHT",
    "HEALTHY_HCT_THRESHOLD",
    "HEALTHY_OVERRIDE_THRESHOLD",
    "CRITICAL_HCT_THRESHOLD",
    "CRITICAL_OVERRIDE_THRESHOLD",
]

DEFAULT_DECAY_LAMBDA: Final[float] = 0.005
MIN_HITS_FOR_EVALUATION: Final[int] = 5
OVERRIDE_WEIGHT: Final[float] = 1.5
HEALTHY_HCT_THRESHOLD: Final[float] = 0.80
HEALTHY_OVERRIDE_THRESHOLD: Final[float] = 0.05
CRITICAL_HCT_THRESHOLD: Final[float] = 0.50
CRITICAL_OVERRIDE_THRESHOLD: Final[float] = 0.15


class RuleHealthTier(str, Enum):
    """Discrete operational health tiers for review rules."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    EVALUATING = "evaluating"


@dataclass(frozen=True)
class RuleDriftMetrics:
    """Hit Confidence Trend and drift classification metrics for a rule."""

    rule_id: str
    hits_total: int
    overrides_total: int
    override_rate: float
    hct: float
    tier: RuleHealthTier
    provisional: bool
    last_hit_utc: str | None = None


def calculate_hct(
    hits: int,
    overrides: int,
    days_since_last_hit: float = 0.0,
) -> float:
    """Calculate Hit Confidence Trend (HCT).

    HCT = max(0.0, 1.0 - (override_rate * 1.5) - (0.005 * days_since_last_hit))
    where override_rate = overrides / hits (or 0.0 if hits == 0).
    """
    if hits <= 0:
        override_rate = 0.0
    else:
        override_rate = overrides / hits

    days = max(0.0, float(days_since_last_hit))
    hct_raw = 1.0 - (override_rate * OVERRIDE_WEIGHT) - (DEFAULT_DECAY_LAMBDA * days)
    return max(0.0, round(hct_raw, 4))


def evaluate_rule_drift(
    rule_id: str,
    hits: int,
    overrides: int,
    days_since_last_hit: float = 0.0,
    last_hit_utc: str | None = None,
) -> RuleDriftMetrics:
    """Evaluate drift metrics and health classification for a single rule."""
    if hits <= 0:
        override_rate = 0.0
    else:
        override_rate = overrides / hits

    hct = calculate_hct(hits, overrides, days_since_last_hit)

    if hits < MIN_HITS_FOR_EVALUATION:
        tier = RuleHealthTier.EVALUATING
        provisional = True
    elif hct < CRITICAL_HCT_THRESHOLD or override_rate >= CRITICAL_OVERRIDE_THRESHOLD:
        tier = RuleHealthTier.CRITICAL
        provisional = False
    elif hct >= HEALTHY_HCT_THRESHOLD and override_rate < HEALTHY_OVERRIDE_THRESHOLD:
        tier = RuleHealthTier.HEALTHY
        provisional = False
    else:
        tier = RuleHealthTier.WARNING
        provisional = False

    return RuleDriftMetrics(
        rule_id=rule_id,
        hits_total=hits,
        overrides_total=overrides,
        override_rate=round(override_rate, 4),
        hct=hct,
        tier=tier,
        provisional=provisional,
        last_hit_utc=last_hit_utc,
    )


def _find_rules_table(conn: sqlite3.Connection) -> str:
    """Determine the name of the review rules table in the SQLite database."""
    for tbl in ("review_rules", "categorization_rules"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (tbl,),
        ).fetchone()
        if row:
            return tbl
    return "review_rules"


def audit_all_rules_drift(
    conn: sqlite3.Connection,
    now_utc: str | None = None,
) -> list[RuleDriftMetrics]:
    """Audit drift metrics and health tiers for all review rules in the database."""
    table_name = _find_rules_table(conn)
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    cols_info = cursor.fetchall()
    if not cols_info:
        # Table does not exist; let standard SELECT fail with OperationalError
        conn.execute(f"SELECT * FROM {table_name}")

    col_names = [c[1] for c in cols_info]
    col_idx = {name: i for i, name in enumerate(col_names)}

    def get_val(r: Any, col: str) -> Any:
        if col not in col_idx:
            return None
        if hasattr(r, "keys"):
            return r[col]
        return r[col_idx[col]]

    rule_id_col = "rule_id" if "rule_id" in col_names else "id"
    rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY {rule_id_col} ASC").fetchall()

    # Check for auxiliary tables
    has_audit_events = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()
        is not None
    )

    has_staged = (
        conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('staged_transactions', 'staged_postings')"
        ).fetchone()[0]
        == 2
    )

    staged_rows: list[tuple[Any, ...]] = []
    if has_staged:
        staged_rows = conn.execute(
            "SELECT st.staged_transaction_id, st.payee, con.account "
            "FROM staged_transactions st "
            "JOIN staged_postings con ON con.staged_transaction_id = st.staged_transaction_id AND con.role = 'contra'"
        ).fetchall()

    results: list[RuleDriftMetrics] = []
    effective_now = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for r in rows:
        r_id = str(get_val(r, rule_id_col))

        # 1. Inspect state columns on rule row if present
        col_hits = 0
        for k in ("hits_total", "total_hits", "hits"):
            v = get_val(r, k)
            if v is not None:
                col_hits = int(v)
                break

        col_overrides = 0
        for k in ("overrides_total", "total_overrides", "override_count", "overrides"):
            v = get_val(r, k)
            if v is not None:
                col_overrides = int(v)
                break

        col_last_hit = None
        for k in ("last_hit_utc", "last_hit", "last_matched_at_utc"):
            v = get_val(r, k)
            if v is not None:
                col_last_hit = str(v)
                break

        # 2. Inspect audit_events table if present
        audit_hits = 0
        audit_overrides = 0
        audit_last_hit = None

        if has_audit_events:
            ev_rows = conn.execute(
                "SELECT action, target, result, ts_utc FROM audit_events "
                "WHERE (action LIKE ? OR target = ?) AND result = 'ok' "
                "ORDER BY seq ASC",
                (f"%{r_id}%", r_id),
            ).fetchall()

            for ev in ev_rows:
                act = ev[0] if not hasattr(ev, "keys") else ev["action"]
                tgt = ev[1] if not hasattr(ev, "keys") else ev["target"]
                ts = ev[3] if not hasattr(ev, "keys") else ev["ts_utc"]

                if tgt == r_id and act in (
                    "rule add",
                    "rule disable",
                    "rule delete",
                    "rule resolve (skipped uncompilable regex)",
                ):
                    continue

                if "override" in act.lower():
                    audit_overrides += 1
                    audit_hits += 1
                    if audit_last_hit is None or ts > audit_last_hit:
                        audit_last_hit = str(ts)
                else:
                    audit_hits += 1
                    if audit_last_hit is None or ts > audit_last_hit:
                        audit_last_hit = str(ts)

        # 3. Inspect staged transactions matching rule pattern
        staged_hits = 0
        staged_overrides = 0
        match_type = get_val(r, "match_type")
        pattern = get_val(r, "pattern")
        target_acc = get_val(r, "target_account")

        if staged_rows and match_type and pattern and target_acc:
            for stx in staged_rows:
                payee = stx[1] if not hasattr(stx, "keys") else stx["payee"]
                actual_con = stx[2] if not hasattr(stx, "keys") else stx["account"]
                cp = canonical_payee(payee or "")
                matched = False
                if match_type == "exact" and cp == pattern:
                    matched = True
                elif match_type == "prefix" and cp.startswith(pattern):
                    matched = True
                elif match_type == "regex":
                    try:
                        if re.search(pattern, cp):
                            matched = True
                    except Exception:
                        pass

                if matched:
                    staged_hits += 1
                    if actual_con and actual_con != target_acc:
                        staged_overrides += 1

        total_hits = max(col_hits, audit_hits, staged_hits)
        total_overrides = max(col_overrides, audit_overrides, staged_overrides)

        last_hit = col_last_hit
        if audit_last_hit:
            if last_hit is None or audit_last_hit > last_hit:
                last_hit = audit_last_hit

        # Compute days since last hit
        days_since_last_hit = 0.0
        explicit_days = get_val(r, "days_since_last_hit")
        if explicit_days is not None:
            days_since_last_hit = float(explicit_days)
        elif last_hit:
            try:
                last_dt = datetime.fromisoformat(last_hit.replace("Z", "+00:00"))
                now_dt = datetime.fromisoformat(effective_now.replace("Z", "+00:00"))
                days_since_last_hit = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)
            except Exception:
                days_since_last_hit = 0.0

        metrics = evaluate_rule_drift(
            rule_id=r_id,
            hits=total_hits,
            overrides=total_overrides,
            days_since_last_hit=days_since_last_hit,
            last_hit_utc=last_hit,
        )
        results.append(metrics)

    return results
