# IronLedger Phase 5 validation suite (IL-GOV-TEST-005)

- **Document ID**: `IL-GOV-TEST-005`
- **Status**: Ratified
- **Ratification Date**: 2026-09-09
- **Domain**: Automated Test Verification & Invariant Assertions

---

## 1. Test strategy

Phase 5 validation enforces high-assurance verification across schemas, API endpoints, safe-mode compile boundaries, and end-to-end integration workflows.

---

## 2. Invariant test matrices

### 2.1 Schema validation matrix (`tests/test_web_schemas.py`)

| Requirement | Test case | Verification result |
|---|---|---|
| Monetary amounts must be integer minor units | `test_posting_schema_valid_integers` | PASS |
| Floating point numbers rejected as minor units | `test_posting_schema_rejects_floats` | PASS |
| Booleans rejected as minor units | `test_posting_schema_rejects_bools` | PASS |
| Invalid currency codes rejected | `test_posting_schema_invalid_currency` | PASS |
| Invalid account names rejected | `test_posting_schema_invalid_account` | PASS |
| Minor-unit scale mismatch rejected | `test_posting_schema_scale_mismatch` | PASS |

### 2.2 Staging review matrix (`tests/test_web_staging.py`)

| Requirement | Test case | Verification result |
|---|---|---|
| Listing returns all staged entries with postings | `test_get_staging_list` | PASS |
| Categorize updates contra account to categorized | `test_categorize_staged_transaction` | PASS |
| Approve updates transaction status to approved | `test_approve_staged_transaction` | PASS |
| Reject updates transaction status with reason | `test_reject_staged_transaction` | PASS |
| Multi-leg split preserves zero-sum balance | `test_split_staged_transaction_balanced` | PASS |
| Unbalanced split rejected with HTTP 400 | `test_split_staged_transaction_unbalanced` | PASS |

### 2.3 Rule and drift matrix (`tests/test_web_rules.py`)

| Requirement | Test case | Verification result |
|---|---|---|
| Rule candidate generator produces regex patterns | `test_rule_candidate_generation` | PASS |
| Rule creation persists into database | `test_create_and_list_rules` | PASS |
| Rule disable toggles active state | `test_disable_rule` | PASS |
| HCT engine calculates drift and hit rates | `test_rule_drift_calculation` | PASS |

### 2.4 Safe-mode compiler matrix (`tests/test_web_compile.py`)

| Requirement | Test case | Verification result |
|---|---|---|
| Compile acquires `.compile.lock` | `test_compile_acquires_lock` | PASS |
| Safe mode rejects compilation without token | `test_compile_safe_mode_gated` | PASS |
| Dry-run simulation produces diff without disk writes | `test_compile_dry_run_simulation` | PASS |
| Projection rebuild updates SQLite cache | `test_projection_rebuild_endpoint` | PASS |

### 2.5 End-to-end integration matrix (`tests/test_phase5_e2e.py`)

| Pipeline stage | Action verified | Status |
|---|---|---|
| **Ingest** | Bank export parsed and loaded into staged tables | PASS |
| **Review** | Query queue, calculate confidence score, categorize contra | PASS |
| **Split** | Split multi-category expense into 2 balanced contra legs | PASS |
| **Rule Learn** | Extract regex candidate and persist rule into database | PASS |
| **Approve** | Transition transaction state from categorized to approved | PASS |
| **Simulation** | Perform dry-run diff check (0 disk mutations, 0 audit rows) | PASS |
| **Compile** | Compile approved entries into Beancount plaintext files | PASS |
| **Projection** | Rebuild projection SQLite database and FTS5 indices | PASS |
| **Balances** | Retrieve hierarchy balances matching exact transaction sums | PASS |
| **Search** | Query FTS5 index and verify match on payee and accounts | PASS |
| **Freshness** | Verify latency status returns `is_fresh: true` | PASS |
| **Audit Trail** | Inspect immutable hash-chained event records | PASS |
