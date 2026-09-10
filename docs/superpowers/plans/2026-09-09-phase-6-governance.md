# Phase 6: Governance, Mutation Ledger & Safe-Mode Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 6 governance subsystem (`src/ironledger/governance/`) providing cryptographically hash-chained mutation logging, Hit Confidence Trend (HCT) rule drift tracking, multi-threshold projection freshness monitoring, hardened schema migrations with checksum & FK verification, and stateless HMAC step-up safe-mode authorization.

**Architecture:** A modular `governance/` package containing standalone, strictly typed modules for mutations, drift, freshness, migrations, and safe mode. All disk and DB changes operate under serialized transactions (`BEGIN IMMEDIATE`) and crash-resilient manifests without runtime `beancount` imports or floating-point numbers.

**Tech Stack:** Python 3.14, SQLite 3 (STRICT tables, WAL mode, foreign keys), HMAC-SHA256, pytest.

## Global Constraints

- Zero `import beancount` across all implementation modules.
- Strict integer minor units for all monetary amounts and weights.
- All timestamps in UTC ISO-8601 with trailing `Z`.
- Plaintext Beancount files remain the sole ground truth.
- `BEGIN IMMEDIATE` for SQLite state transitions that allocate monotonic sequence numbers.

---

### Task 6.1: Mutation Ledger Engine & Tamper Verification

**Files:**
- Create: `src/ironledger/governance/mutations.py`
- Create: `src/ironledger/governance/__init__.py`
- Modify: `src/ironledger/mutation.py` (Compatibility alias delegation)
- Test: `tests/test_governance_mutations.py`

**Interfaces:**
- Produces:
  - `class MutationEvent` (dataclass)
  - `class MutationVerificationResult` (dataclass)
  - `append_mutation_event(conn: sqlite3.Connection, *, operator_session: str, action: str, staged_count: int, rules_applied: int, rules_created: int, sha256_before: str, sha256_after: str, mutation_id: str | None = None, ts_utc: str | None = None, audit_seq: int | None = None) -> MutationEvent`
  - `verify_mutation_chain(source: sqlite3.Connection | list[MutationEvent]) -> MutationVerificationResult`
  - `compute_canonical_ledger_manifest_hash(ledger_dir: Path | str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_mutations.py`:
```python
import sqlite3
import pytest
from pathlib import Path
from ironledger.db.migrations import migrate
from ironledger.governance.mutations import (
    append_mutation_event,
    verify_mutation_chain,
    compute_canonical_ledger_manifest_hash,
    MutationVerificationError,
    GENESIS_MUTATION_PREV_HASH,
)

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    yield conn
    conn.close()

def test_mutation_chain_lifecycle(db):
    h0 = compute_canonical_ledger_manifest_hash(Path("."))
    ev1 = append_mutation_event(
        db,
        operator_session="sess_1",
        action="compile",
        staged_count=2,
        rules_applied=1,
        rules_created=0,
        sha256_before=h0,
        sha256_after="1" * 64,
    )
    assert ev1.seq == 1
    assert ev1.prev_mutation_hash == GENESIS_MUTATION_PREV_HASH
    assert len(ev1.mutation_hash) == 64

    res = verify_mutation_chain(db)
    assert res.is_valid is True
    assert res.mutation_count == 1
    assert res.head_hash == ev1.mutation_hash

def test_tamper_detection(db):
    h0 = "0" * 64
    append_mutation_event(
        db,
        operator_session="sess_1",
        action="compile",
        staged_count=1,
        rules_applied=0,
        rules_created=0,
        sha256_before=h0,
        sha256_after="a" * 64,
    )
    # Direct DB trigger prevents update, so bypass trigger in test to simulate file rewrite
    db.execute("DROP TRIGGER IF EXISTS trg_mutation_events_no_update")
    db.execute("UPDATE mutation_events SET staged_count = 99 WHERE seq = 1")
    
    with pytest.raises(MutationVerificationError, match="hash mismatch"):
        verify_mutation_chain(db)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_governance_mutations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.governance'`

- [ ] **Step 3: Implement `governance/__init__.py` and `governance/mutations.py`**

Create `src/ironledger/governance/__init__.py` and `src/ironledger/governance/mutations.py` with manifest hashing, `BEGIN IMMEDIATE` serialization, and canonical verification.
Update `src/ironledger/mutation.py` to import and expose symbols from `ironledger.governance.mutations`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_governance_mutations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/governance/ tests/test_governance_mutations.py src/ironledger/mutation.py
git commit -m "feat(governance): implement mutation ledger engine and chain verification"
```

---

### Task 6.2: Hit Confidence Trend (HCT) Rule Drift Tracker

**Files:**
- Create: `src/ironledger/governance/drift.py`
- Test: `tests/test_governance_drift.py`

**Interfaces:**
- Produces:
  - `class RuleHealthTier(str, Enum)`: `HEALTHY = "healthy"`, `WARNING = "warning"`, `CRITICAL = "critical"`, `EVALUATING = "evaluating"`
  - `class RuleDriftMetrics` (dataclass with `rule_id`, `hits_total`, `overrides_total`, `override_rate`, `hct`, `tier`, `provisional`)
  - `calculate_hct(hits: int, overrides: int, days_since_last_hit: float = 0.0) -> float`
  - `evaluate_rule_drift(rule_id: str, hits: int, overrides: int, days_since_last_hit: float = 0.0) -> RuleDriftMetrics`
  - `audit_all_rules_drift(conn: sqlite3.Connection) -> list[RuleDriftMetrics]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_drift.py`:
```python
import pytest
from ironledger.governance.drift import (
    calculate_hct,
    evaluate_rule_drift,
    RuleHealthTier,
)

def test_hct_calculation():
    # 0 overrides, fresh -> 1.0
    assert calculate_hct(100, 0, 0.0) == 1.0
    # 10% override rate -> 1.0 - (0.10 * 1.5) = 0.85
    assert pytest.approx(calculate_hct(100, 10, 0.0), 0.001) == 0.85
    # Decay over 10 days at lambda = 0.005 -> 0.05 reduction
    assert pytest.approx(calculate_hct(100, 0, 10.0), 0.001) == 0.95

def test_health_tiering():
    # Low sample count < 5 -> evaluating
    m1 = evaluate_rule_drift("r1", hits=3, overrides=0)
    assert m1.tier == RuleHealthTier.EVALUATING
    assert m1.provisional is True

    # Healthy: HCT >= 0.80 and O_R < 0.05
    m2 = evaluate_rule_drift("r2", hits=100, overrides=2)
    assert m2.tier == RuleHealthTier.HEALTHY

    # Warning: 0.05 <= O_R < 0.15
    m3 = evaluate_rule_drift("r3", hits=100, overrides=8)
    assert m3.tier == RuleHealthTier.WARNING

    # Critical: O_R >= 0.15
    m4 = evaluate_rule_drift("r4", hits=100, overrides=20)
    assert m4.tier == RuleHealthTier.CRITICAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_governance_drift.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.governance.drift'`

- [ ] **Step 3: Implement `src/ironledger/governance/drift.py`**

Implement formula:
$$\text{HCT}_R = \max\Big(0.0, 1.0 - (\mathcal{O}_R \times 1.5) - 0.005 \cdot \Delta t_{\text{days}}\Big)$$
and full database querying logic against `review_rules` and `audit_events`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_governance_drift.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/governance/drift.py tests/test_governance_drift.py
git commit -m "feat(governance): implement HCT rule drift tracker and health classification"
```

---

### Task 6.3: Projection Freshness & SLA Monitoring

**Files:**
- Create: `src/ironledger/governance/freshness.py`
- Test: `tests/test_governance_freshness.py`

**Interfaces:**
- Produces:
  - `class FreshnessTier(str, Enum)`: `FRESH = "fresh"`, `STALE = "stale"`, `CRITICAL = "critical"`
  - `class ProjectionFreshnessResult` (dataclass with `status`, `latency_seconds`, `source_hash_match`, `ledger_source_sha256`, `projection_source_sha256`)
  - `evaluate_projection_freshness(ledger_source_sha256: str, projection_source_sha256: str, built_at_utc: str, now_utc: str | None = None) -> ProjectionFreshnessResult`

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_freshness.py`:
```python
import pytest
from ironledger.governance.freshness import (
    evaluate_projection_freshness,
    FreshnessTier,
)

def test_freshness_latency_tiers():
    h = "a" * 64
    # Fresh: < 5s
    res1 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:03Z")
    assert res1.status == FreshnessTier.FRESH
    assert res1.latency_seconds == 3.0

    # Stale: 5-30s
    res2 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:15Z")
    assert res2.status == FreshnessTier.STALE
    assert res2.latency_seconds == 15.0

    # Critical: > 30s
    res3 = evaluate_projection_freshness(h, h, "2026-09-09T20:00:00Z", "2026-09-09T20:00:45Z")
    assert res3.status == FreshnessTier.CRITICAL
    assert res3.latency_seconds == 45.0

def test_hash_mismatch_forces_critical():
    # Even with 0s latency, hash mismatch triggers CRITICAL
    res = evaluate_projection_freshness("a" * 64, "b" * 64, "2026-09-09T20:00:00Z", "2026-09-09T20:00:00Z")
    assert res.status == FreshnessTier.CRITICAL
    assert res.source_hash_match is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_governance_freshness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.governance.freshness'`

- [ ] **Step 3: Implement `src/ironledger/governance/freshness.py`**

Implement unidirectional latency checks, clock rollback clamps, and live hash divergence detection.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_governance_freshness.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/governance/freshness.py tests/test_governance_freshness.py
git commit -m "feat(governance): implement projection freshness evaluator and SLA tiers"
```

---

### Task 6.4: Forward-Only Migration Engine Hardening

**Files:**
- Create: `src/ironledger/governance/migrations.py`
- Modify: `src/ironledger/db/migrations.py` (Compatibility alias delegation)
- Test: `tests/test_governance_migrations.py`

**Interfaces:**
- Produces:
  - `migrate_governed(conn: sqlite3.Connection, directory: str | Path | None = None) -> int`
  - `verify_schema_checksums(conn: sqlite3.Connection, directory: str | Path | None = None) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_migrations.py`:
```python
import sqlite3
import pytest
from pathlib import Path
from ironledger.governance.migrations import (
    migrate_governed,
    verify_schema_checksums,
    MigrationError,
)

def test_migration_fk_enforcement(tmp_path):
    conn = sqlite3.connect(tmp_path / "test.db")
    
    # Write invalid migration with broken FK
    mig_dir = tmp_path / "schema"
    mig_dir.mkdir()
    (mig_dir / "0001_initial.sql").write_text(
        "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT;\n"
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id)) STRICT;\n",
        encoding="utf-8"
    )
    (mig_dir / "0002_bad_fk.sql").write_text(
        "PRAGMA defer_foreign_keys = ON;\n"
        "INSERT INTO child (id, parent_id) VALUES (1, 999);\n",
        encoding="utf-8"
    )
    
    with pytest.raises(MigrationError, match="foreign key check failed"):
        migrate_governed(conn, directory=mig_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_governance_migrations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.governance.migrations'`

- [ ] **Step 3: Implement `src/ironledger/governance/migrations.py`**

Implement pre-flight checksum check, `BEGIN IMMEDIATE`, `PRAGMA foreign_keys = ON;`, and `PRAGMA foreign_key_check;` validation before committing.
Update `src/ironledger/db/migrations.py` to delegate to `governance.migrations`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_governance_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/governance/migrations.py tests/test_governance_migrations.py src/ironledger/db/migrations.py
git commit -m "feat(governance): harden migration runner with pre-flight checksums and FK checks"
```

---

### Task 6.5: Safe-Mode Mutation Gate & Stateless Step-Up Tokens

**Files:**
- Create: `src/ironledger/governance/safemode.py`
- Modify: `src/ironledger/cli/auth.py`
- Modify: `src/ironledger/web/routers/compile.py`
- Modify: `src/ironledger/web/routers/system.py`
- Test: `tests/test_governance_safemode.py`

**Interfaces:**
- Produces:
  - `create_step_up_token(secret: str | bytes, *, actor: str, scope: str, target_digest: str, ttl_seconds: int = 300, now_epoch: int | None = None) -> str`
  - `verify_step_up_token(token: str, secret: str | bytes, expected_scope: str, expected_target_digest: str, now_epoch: int | None = None) -> dict`
  - `require_governed_authorization(conn: sqlite3.Connection, *, token: str | None, scope: str, target_digest: str, config_dir: Path | str, actor: str = "operator") -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_safemode.py`:
```python
import sqlite3
import pytest
import time
from pathlib import Path
from ironledger.db.migrations import migrate
from ironledger.governance.safemode import (
    create_step_up_token,
    verify_step_up_token,
    require_governed_authorization,
    SafeModeAuthorizationError,
)

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    yield conn
    conn.close()

def test_token_creation_and_verification():
    secret = "test-safe-mode-secret-key-12345"
    token = create_step_up_token(
        secret,
        actor="ops_admin",
        scope="compile",
        target_digest="d" * 64,
        ttl_seconds=300,
    )
    payload = verify_step_up_token(token, secret, expected_scope="compile", expected_target_digest="d" * 64)
    assert payload["actor"] == "ops_admin"
    assert payload["scope"] == "compile"

def test_token_expiration():
    secret = "test-secret"
    now = int(time.time())
    token = create_step_up_token(
        secret,
        actor="ops",
        scope="compile",
        target_digest="a" * 64,
        ttl_seconds=10,
        now_epoch=now - 20,
    )
    with pytest.raises(SafeModeAuthorizationError, match="expired"):
        verify_step_up_token(token, secret, "compile", "a" * 64, now_epoch=now)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_governance_safemode.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.governance.safemode'`

- [ ] **Step 3: Implement `src/ironledger/governance/safemode.py` and unify API/CLI gates**

Implement HMAC validation, nonces, `iat`/`exp` window checks, and centralized `require_governed_authorization` writing to `audit_events`.
Update `src/ironledger/web/routers/compile.py` to route through `require_governed_authorization`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_governance_safemode.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/governance/safemode.py tests/test_governance_safemode.py src/ironledger/web/routers/compile.py src/ironledger/cli/auth.py
git commit -m "feat(governance): implement stateless HMAC step-up safe mode gate and router protection"
```

---

### Task 6.6: End-to-End Governance Acceptance Suite & Ratification Evidence

**Files:**
- Create: `tests/test_governance_e2e.py`
- Create: `docs/meta/phases/ironledger-phase-6-evidence.md`

- [ ] **Step 1: Write the end-to-end integration test**

Create `tests/test_governance_e2e.py` validating a complete sequence: migration pre-flight $\to$ step-up token generation $\to$ authorized compile with `BEGIN IMMEDIATE` $\to$ mutation chain appending $\to$ drift & freshness evaluation $\to$ audit logging.

- [ ] **Step 2: Run full regression test suite**

Run: `python -m pytest tests/ -v`
Expected: 100% tests passing across all suites.

- [ ] **Step 3: Generate phase exit evidence**

Write `docs/meta/phases/ironledger-phase-6-evidence.md` documenting test run metrics, zero `import beancount` verification, and schema integrity audit.

- [ ] **Step 4: Commit**

```bash
git add tests/test_governance_e2e.py docs/meta/phases/ironledger-phase-6-evidence.md
git commit -m "chore(phase6): finalize governance acceptance suite and exit evidence"
```

---
