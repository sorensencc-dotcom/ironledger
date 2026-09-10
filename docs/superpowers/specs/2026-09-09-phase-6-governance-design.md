# IronLedger Phase 6: Governance, Mutation Ledger & Safe-Mode Migration Design Specification

- **Document ID**: `IL-SPEC-2026-09-09-GOV`
- **Target Phase**: Phase 6 — Governance, Mutation Ledger Hardening & Safe-Mode Migration Infrastructure
- **Status**: Draft / Under Review
- **Authors**: IronLedger Architecture Team
- **Reviewed By**: OpenAI Codex Independent Architectural Review (Incorporated)

---

## 1. Executive Summary & Architectural Invariants

Phase 6 formalizes IronLedger's operational governance: tracking ledger drift, managing migration lifecycles, and hardening mutating operations behind a cryptographically chained append-only mutation ledger and safe-mode gates.

### Core Invariants

1. **Plaintext Ground Truth**: Plaintext Beancount files on disk remain the sole financial authority. SQLite databases (`ironledger.db` and `projection.db`) are strictly derivative and disposable.
2. **Decoupled Runtime**: Zero `import beancount` anywhere in core application code. All syntax checking and compilation validation run via subprocess invocation (`bean-check`).
3. **Integer Minor-Unit Arithmetic**: Zero floating-point representation in storage, calculations, or network serialization.
4. **Tamper-Evident Hash Chaining**: Every state-altering mutation appends a monotonic, SHA-256 chained event starting from Genesis ($0^{64}$).
5. **Fail-Closed Safe Mode**: Mutating endpoints and CLI operations fail closed unless unlocked via time-bounded, cryptographic step-up authorization tokens.
6. **Crash-Resilient State Machine**: Multi-step operations touching disk and SQLite follow a deterministic state progression (`intent` $\to$ `staged` $\to$ `validated` $\to$ `activated` $\to$ `verified` $\to$ `committed`) with idempotency keys.

---

## 2. Directory Layout & Module Architecture

All governance, drift detection, freshness tracking, and authorization logic are housed in a dedicated `src/ironledger/governance/` subsystem to preserve Phase 5 stability while providing a clear runway for Phase 7:

```
src/ironledger/governance/
├── __init__.py          # Exports public governance API
├── mutations.py         # Task 6.1: Mutation chain verification & ledger integrity
├── drift.py             # Task 6.2: Hit Confidence Trend (HCT), Override Rate & health tiering
├── freshness.py         # Task 6.3: Multi-threshold projection SLA & hash sync delta
├── migrations.py        # Task 6.4: Schema checksum validation, transaction isolation, FK checks
└── safemode.py          # Task 6.5: Stateless HMAC step-up tokens & safe-mode policy gate
```

Backward-compatibility shims will be preserved in `src/ironledger/mutation.py`, `src/ironledger/db/migrations.py`, and `src/ironledger/cli/auth.py` delegating to `ironledger.governance.*`.

---

## 3. Detailed Component Specifications

### 3.1 Task 6.1: Mutation Ledger Engine & Chain Verification (`governance/mutations.py`)

#### Monotonic Sequence & Write Serialization
To eliminate race conditions across concurrent processes, sequence allocation and chain appending must use `BEGIN IMMEDIATE` transaction blocks in SQLite:

```sql
BEGIN IMMEDIATE;
-- 1. Read latest seq and mutation_hash
-- 2. Validate monotonic seq = last_seq + 1
-- 3. Validate prev_mutation_hash = last_hash
-- 4. Insert mutation_events row
-- 5. Link to audit_events sequence
COMMIT;
```

#### Canonical Digest Computation
Each mutation event satisfies:
$$H_k = \text{SHA-256}\Big(\text{canonical\_json}\big(\text{seq}_k, \text{id}_k, \text{ts}_k, \text{actor}_k, \text{action}_k, C_{\text{staged}}, C_{\text{applied}}, C_{\text{created}}, S_{\text{before}}, S_{\text{after}}, H_{k-1}\big)\Big)$$

Where $S_{\text{before}}$ and $S_{\text{after}}$ are computed from a canonical disk manifest over all `.beancount` ledger files:
$$\text{Manifest} = \text{Sorted}\Big(\big[\text{relpath}, \text{filesize}, \text{sha256(content)}\big]\Big)$$
*(Transient files, `.staging.lock`, and `.tmp` files are explicitly excluded from the manifest calculation).*

---

### 3.2 Task 6.2: Hit Confidence Trend (HCT) Drift Tracking (`governance/drift.py`)

#### Metric Formulation & Reconciled Policy
Reconciling `IL-GOV-SPEC-006` and `IL-GOV-DRIFT-001`, rule health is governed by:

1. **Override Rate ($\mathcal{O}_R$)**:
   $$\mathcal{O}_R = \frac{N_{\text{overrides}}}{N_{\text{total}}}$$
2. **Hit Confidence Trend ($\text{HCT}_R$)**:
   $$\text{HCT}_R = \max\Big(0.0, 1.0 - (\mathcal{O}_R \times 1.5) - \lambda \cdot \Delta t_{\text{days}}\Big)$$
   *(where $\lambda = 0.005$ day$^{-1}$ rolling decay factor).*

#### Health Classification Tiers
| Tier | Status | Criteria | Operational Gate |
|---|---|---|---|
| **Tier 1** | `healthy` | $\text{HCT} \ge 0.80$ and $\mathcal{O}_R < 0.05$ | Automated matching & bulk approval allowed. |
| **Tier 2** | `warning` | $0.50 \le \text{HCT} < 0.80$ or $0.05 \le \mathcal{O}_R < 0.15$ | Visual amber badge; automated matching disabled. |
| **Tier 3** | `critical` / `stale` | $\text{HCT} < 0.50$ or $\mathcal{O}_R \ge 0.15$ | Rule flagged for deprecation; matching gated. |

*Minimum sample size constraint*: Rules with $N_{\text{total}} < 5$ are tagged as `evaluating` ($\text{HCT} = 1.0, \text{tier} = \text{healthy}$ with provisional flag).

---

### 3.3 Task 6.3: Projection Freshness & SLA Daemon (`governance/freshness.py`)

#### Latency Calculation
Freshness measures elapsed time since the last successful projection build:
$$\Delta t = \max\big(0.0, t_{\text{current\_utc}} - t_{\text{last\_projection\_build\_utc}}\big)$$

#### Hash Divergence Condition
Projection metadata stores `ledger_source_sha256`. The freshness engine compares this against the live canonical disk manifest hash.

#### SLA Thresholds
- **`fresh` / Synced**: $\Delta t < 5.0\,\text{s}$ AND `disk_hash == projection_source_hash`.
- **`stale`**: $5.0\,\text{s} \le \Delta t \le 30.0\,\text{s}$ AND `disk_hash == projection_source_hash`.
- **`critical` / Desync**: $\Delta t > 30.0\,\text{s}$ OR `disk_hash != projection_source_hash`. (Blocks automated compile and strict query endpoints).

---

### 3.4 Task 6.4: Migration Engine Hardening (`governance/migrations.py`)

1. **Pre-Flight Manifest Validation**: Validates SHA-256 checksums of *all* migration files against a committed schema manifest before executing any pending migrations.
2. **Transaction Isolation & FK Enforcement**:
   - Acquires `BEGIN IMMEDIATE`.
   - Sets `PRAGMA foreign_keys = ON;`.
   - Executes migration SQL.
   - Executes `PRAGMA foreign_key_check;`. If any violation exists, raises `MigrationError` and triggers `ROLLBACK`.
   - Records version into `schema_migrations` and commits.

---

### 3.5 Task 6.5: Safe-Mode Mutation Gate & Hardened Step-Up Tokens (`governance/safemode.py`)

#### Token Construction
Stateless step-up tokens use HMAC-SHA256 with nonce and scope bindings:
$$\text{Payload} = \big\{\text{jti}, \text{actor}, \text{scope}, \text{target\_digest}, \text{iat}, \text{exp}\big\}$$
$$\text{Token} = \text{base64url}(\text{Payload}) \mathbin{\Vert} "." \mathbin{\Vert} \text{HMAC-SHA256}(K, \text{base64url}(\text{Payload}))$$

#### Hardened Validation Rules:
1. **TTL Window**: Maximum $900\,\text{s}$ (15 minutes). $\text{exp} - \text{iat} \le 900$.
2. **Clock Skew**: Rejects tokens with $\text{iat} > \text{now} + 30\,\text{s}$.
3. **Idempotency & Replay Resistance**: Destructive actions bind $\text{jti}$ and $\text{target\_digest}$ to ensure single-use execution.
4. **Fail-Closed Configuration**: Missing, unreadable, symlinked, or corrupted `config/safe-mode.json` defaults strictly to `Safe Mode Active`.
5. **Unified Enforcement**: Harmonizes `POST /api/compile`, `POST /api/project/rebuild`, and CLI commands to use this centralized gate. Denied attempts append a `denied` event to `audit_events`.

---

## 4. Test & Verification Matrix

| Test Suite | Focus | Key Assertions |
|---|---|---|
| `tests/test_governance_mutations.py` | `governance/mutations.py` | Sequence gap detection, tamper invalidation, `BEGIN IMMEDIATE` concurrency serialization. |
| `tests/test_governance_drift.py` | `governance/drift.py` | Exact HCT mathematical compliance, sliding window decay, override rate tier transitions. |
| `tests/test_governance_freshness.py` | `governance/freshness.py` | Clock skew handling, unidirectional latency tiers, live disk hash mismatch $\to$ `critical`. |
| `tests/test_governance_migrations.py` | `governance/migrations.py` | Pre-flight checksum check, FK check abort & rollback, atomic schema migration commit. |
| `tests/test_governance_safemode.py` | `governance/safemode.py` | HMAC verification, TTL expiration, invalid scope rejection, fail-closed config reading, denied audit logging. |

---
