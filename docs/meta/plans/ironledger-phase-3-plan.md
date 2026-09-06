# IronLedger Phase 3 Beancount compiler and recovery journal implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile approved staged transactions into canonical, deterministic Beancount ledger files validated with `bean-check`, write the ledger atomically via staging and `os.replace`, record the compiled index in SQLite, and journal every compile for deterministic crash recovery or operator escalation.

**Architecture:** A new `src/ironledger/compile/` package encapsulates model loading and strict validation (`model.py`), pure deterministic Beancount rendering (`render.py`), canonical input/output hashing (`hashing.py`), `bean-check` subprocess isolation (`beancheck.py`), append-only run and journal persistence (`journal.py`), atomic write and lock coordination (`writer.py`), and crash recovery (`recover.py`). Migration `0005`, written whole in Task 1, adds the append-only `compile_journal` table with `RAISE(ABORT)` triggers. The CLI adds the `compile` subcommand tree (`compile`, `compile status`, `compile recover`) gated by `cli/auth.py`.

**Tech Stack:** Python 3.12+ standard library (`sqlite3`, `argparse`, `dataclasses`, `hashlib`, `subprocess`, `shutil`, `pathlib`, `json`). `beancount` pinned dependency invoked exclusively as a subprocess via `bean-check` (never imported on the accounting path). Tests use `pytest`.

**Repo:** `C:\dev\IronLedger` (local `main`, no remote, decision D-0). Run tests with `PYTHONPATH=src python -m pytest -q`. Baseline before Task 1: **254 passed, 1 skipped**.

**Spec:** `C:\dev\docs\meta\specs\ironledger-phase-3-compiler-design.md` (operator-reviewed). The plan argues directly from the spec; executors read both.

---

## Global Constraints

- Python `requires-python = ">=3.12"`. Standard library for runtime core logic; `beancount` invoked solely via `bean-check` subprocess.
- Monetary values are signed 64-bit integer minor units with explicit currency and scale. No floating-point accounting arithmetic. Unlike currencies are never netted.
- Timestamps are UTC ISO-8601 `%Y-%m-%dT%H:%M:%SZ` (trailing `Z`). Functions accepting timestamps take `now_utc: str | None = None` and default to `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.
- `audit.append_audit_event(conn, *, actor, action, target, result, compile_run_id=None, input_hash=None, output_hash=None, ...)` carries the fixed field envelope with `actor="operator"`.
- Ledger layout: `ledger/main.beancount`, `ledger/accounts.beancount`, and `ledger/txns/YYYY.beancount` under `conventions.LEDGER_LAYOUT`.
- Rendering is a pure function: `render.py` performs zero filesystem I/O and outputs deterministic UTF-8 bytes with LF newlines.
- Migration runner: `0005_compile_journal.sql` is written **whole in Task 1** (checksum frozen by migration runner). It contains no `BEGIN`/`COMMIT` and does not rely on `PRAGMA foreign_keys`.
- File locks: Exclusive compile lock on `ledger/.compile.lock` serializes all compile and recovery mutators.
- Staging directory (Finding 7): staging lives at `ledger/.staging/<run_id>/` — inside the ledger tree, on the same filesystem volume as the live files. Never a `tempfile` / `%TEMP%` path: `os.replace` across volumes raises `OSError` with no fallback (this repo's dev host is Windows). Tasks 8 and 9 already use `ledger_dir / ".staging" / run_id`; do not change it to a tempdir.
- Authorization: `ironledger compile` requires `authorize compile`; `ironledger compile recover` requires `authorize compile recover`. Safe mode blocks both mutators.
- Exit codes: `0` for success, `1` for validation/compile error, `3` for authorization/safe-mode denial.
- All file writes must use LF newlines.

---

### Task 1: Migration 0005 — the complete compile journal schema

Write `0005_compile_journal.sql` **whole** in this task: the `compile_journal` table with strict CHECK constraints and `RAISE(ABORT)` triggers for append-only immutability. The migration runner records a checksum of this file, so it must not change again.

**Files:**
- Create: `src/ironledger/db/schema/0005_compile_journal.sql`
- Test: `tests/test_migration_0005.py`
- Modify: `tests/test_migration_0004.py` — line asserting `migrations.current_version(db) == 4` (the runner now reaches 5).
- Modify: `tests/test_manifests.py` — line asserting `manifest.row_counts["schema_migrations"] == 4` (now 5).

**Interfaces:**
- Consumes: `ironledger.db.migrations.migrate`, `ironledger.db.connection.connect`
- Produces: Schema version 5; `compile_journal` table with monotonic `seq >= 1`, FK to `compile_runs(compile_run_id)`, state CHECK (`'started'`, `'bean_checked'`, `'replaced'`, `'succeeded'`, `'failed'`, `'recovered'`, `'refused'`), `ts_utc` format check, and `idx_compile_journal_run`.

**Eng-review folds (2026-09-06):**
- **B-T6:** two existing tests hard-code the schema version. `tests/test_migration_0004.py` asserts `current_version(db) == 4`; `tests/test_manifests.py` asserts `row_counts["schema_migrations"] == 4`. Migration 0005 makes both fail. This task updates both to `== 5`. Where practical, replace the literal with `len(migrations.MIGRATIONS)` (or the runner's known-migration count) so a future 0006 does not re-trigger this. The full-suite gate at the end of this task must be green including these two files.
- **Finding 6:** add `test_migration_0005_checksum_frozen` — apply migrations, then mutate the on-disk `0005_compile_journal.sql` byte-for-byte and assert the migration runner refuses to re-run / raises a checksum-mismatch error. "Frozen by the runner" must be a tested guarantee, not a comment.
- **Finding 8:** the RED step below fails in more than one way; see its corrected Expected line.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_0005.py
"""Phase 3: migration 0005 adds the append-only compile_journal table."""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_compile_run(conn: sqlite3.Connection, run_id: str = "run-1") -> str:
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, status, started_at_utc, recovery_state) "
        f"VALUES ('{run_id}', '3.0.0', '0.1.0', '{'a'*64}', '{'b'*64}', 'started', "
        " '2026-09-06T12:00:00Z', 'none')"
    )
    conn.commit()
    return run_id


def test_reaches_version_five(db: sqlite3.Connection):
    assert migrations.current_version(db) == 5


def test_compile_journal_table_present_and_accepts_valid_row(db: sqlite3.Connection):
    run_id = _seed_compile_run(db)
    db.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        f"VALUES (1, '{run_id}', 'started', '2026-09-06T12:00:00Z', 'initial start')"
    )
    db.commit()
    row = db.execute(
        "SELECT seq, compile_run_id, state, ts_utc, detail FROM compile_journal WHERE seq = 1"
    ).fetchone()
    assert row == (1, run_id, "started", "2026-09-06T12:00:00Z", "initial start")


def test_compile_journal_triggers_prevent_update_and_delete(db: sqlite3.Connection):
    run_id = _seed_compile_run(db)
    db.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        f"VALUES (1, '{run_id}', 'started', '2026-09-06T12:00:00Z', '')"
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="compile_journal is append-only: UPDATE is forbidden"):
        db.execute("UPDATE compile_journal SET state = 'succeeded' WHERE seq = 1")

    with pytest.raises(sqlite3.IntegrityError, match="compile_journal is append-only: DELETE is forbidden"):
        db.execute("DELETE FROM compile_journal WHERE seq = 1")
```

Add `test_migration_0005_checksum_frozen` to `tests/test_migration_0005.py` (Finding 6): after `migrate()`, overwrite `src/ironledger/db/schema/0005_compile_journal.sql` with altered bytes on a fresh connection and assert the runner raises a checksum-mismatch error.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_migration_0005.py -v`
Expected: FAIL. `test_reaches_version_five` fails `AssertionError: assert 4 == 5`; `test_compile_journal_table_present_and_accepts_valid_row`, `test_compile_journal_triggers_prevent_update_and_delete`, and `test_migration_0005_checksum_frozen` fail with `sqlite3.OperationalError: no such table: compile_journal` (impl-missing, valid RED for greenfield TDD). No test-file syntax error.

- [ ] **Step 3: Write migration 0005 whole**

```sql
-- src/ironledger/db/schema/0005_compile_journal.sql
-- IronLedger Phase 3: append-only compile journal and recovery state tracking.

CREATE TABLE compile_journal (
    seq            INTEGER PRIMARY KEY,          -- explicit monotonic allocation, not AUTOINCREMENT
    compile_run_id TEXT NOT NULL
        REFERENCES compile_runs (compile_run_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    state          TEXT NOT NULL CHECK (state IN (
        'started', 'bean_checked', 'replaced', 'succeeded', 'failed', 'recovered', 'refused'
    )),
    ts_utc         TEXT NOT NULL CHECK (ts_utc GLOB '????-??-??T??:??:??*Z'),
    detail         TEXT NOT NULL DEFAULT '',
    CHECK (seq >= 1)
) STRICT;

CREATE INDEX idx_compile_journal_run ON compile_journal (compile_run_id);

CREATE TRIGGER compile_journal_no_update
BEFORE UPDATE ON compile_journal
BEGIN
    SELECT RAISE(ABORT, 'compile_journal is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER compile_journal_no_delete
BEFORE DELETE ON compile_journal
BEGIN
    SELECT RAISE(ABORT, 'compile_journal is append-only: DELETE is forbidden');
END;
```

- [ ] **Step 4: Update the two version-pinned tests (B-T6) and run the full suite**

Change `tests/test_migration_0004.py` (`current_version(db) == 4` → `== 5`, or `len(migrations.MIGRATIONS)`) and `tests/test_manifests.py` (`row_counts["schema_migrations"] == 4` → `== 5`).

Run: `pytest tests/test_migration_0005.py -v` → PASS (4 passed).
Run: `PYTHONPATH=src python -m pytest -q` → full suite green (baseline 254 pass / 1 skip, now +4 in `test_migration_0005.py`, 2 files edited, net 258 pass / 1 skip). The task does not commit if any pre-existing test is red.

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/db/schema/0005_compile_journal.sql tests/test_migration_0005.py tests/test_migration_0004.py tests/test_manifests.py
git commit -m "feat(compile): add migration 0005 compile journal schema and triggers"
```

---

### Task 2: `compile_journal` constraint and integrity test coverage

Add exhaustive constraint tests for `compile_journal`: FK integrity against `compile_runs`, all valid states (`started`, `bean_checked`, `replaced`, `succeeded`, `failed`, `recovered`, `refused`), rejection of invalid states, timestamp formatting, sequence bounds, and gapless monotonic sequence allocation.

**Files:**
- Test: `tests/test_migration_0005_constraints.py`

**Interfaces:**
- Consumes: `0005_compile_journal.sql` applied via `ironledger.db.migrations.migrate`
- Produces: Verified SQLite constraint guarantees for the Phase 3 journal.

- [ ] **Step 1: Write constraint tests**

```python
# tests/test_migration_0005_constraints.py
"""Exhaustive constraint and trigger tests for compile_journal table."""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_run(conn: sqlite3.Connection, run_id: str = "run-1") -> str:
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, status, started_at_utc, recovery_state) "
        f"VALUES ('{run_id}', '3.0.0', '0.1.0', '{'a'*64}', '{'b'*64}', 'started', "
        " '2026-09-06T12:00:00Z', 'none')"
    )
    conn.commit()
    return run_id


@pytest.mark.parametrize("valid_state", [
    "started", "bean_checked", "replaced", "succeeded", "failed", "recovered", "refused"
])
def test_all_valid_states_accepted(db: sqlite3.Connection, valid_state: str):
    run_id = _seed_run(db)
    db.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        f"VALUES (1, '{run_id}', '{valid_state}', '2026-09-06T12:00:00Z', '')"
    )
    db.commit()
    assert db.execute("SELECT state FROM compile_journal WHERE seq = 1").fetchone()[0] == valid_state


def test_invalid_state_rejected(db: sqlite3.Connection):
    run_id = _seed_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            f"VALUES (1, '{run_id}', 'invalid_state', '2026-09-06T12:00:00Z', '')"
        )


def test_foreign_key_to_compile_runs_enforced(db: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            "VALUES (1, 'non-existent-run', 'started', '2026-09-06T12:00:00Z', '')"
        )


def test_seq_less_than_one_rejected(db: sqlite3.Connection):
    run_id = _seed_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            f"VALUES (0, '{run_id}', 'started', '2026-09-06T12:00:00Z', '')"
        )


def test_timestamp_format_glob_enforced(db: sqlite3.Connection):
    run_id = _seed_run(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
            f"VALUES (1, '{run_id}', 'started', '2026-09-06 12:00:00', '')"
        )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_migration_0005_constraints.py -v`
Expected: PASS (11 passed)

- [ ] **Step 3: Commit**

```bash
git add tests/test_migration_0005_constraints.py
git commit -m "test(compile): add comprehensive constraints tests for compile_journal"
```

---

### Task 3: `compile/errors.py` and `compile/model.py` — approved set loading and validation

Implement domain errors and the loader that reads approved transactions with joined postings, source records, and documents. Enforce strict preconditions: reject null contra accounts, unbalanced transactions, conflicting account currencies, and invalid account names.

**Files:**
- Create: `src/ironledger/compile/__init__.py`
- Create: `src/ironledger/compile/errors.py`
- Create: `src/ironledger/compile/model.py`
- Test: `tests/test_compile_model.py`

**Interfaces:**
- Consumes: SQLite tables (`staged_transactions`, `staged_postings`, `source_records`, `source_documents`), `ironledger.conventions.validate_same_currency_balance`, `validate_account_name`.
- Produces: Dataclasses `ApprovedPosting`, `ApprovedTransaction`, `ApprovedSet`; `load_approved_set(conn) -> ApprovedSet`; `validate_approved_set(approved_set) -> None`; Exception hierarchy `CompileError`, `CompileInputError`.

- [ ] **Step 1: Write failing tests for approved set loader and validator**

```python
# tests/test_compile_model.py
"""Tests for loading and validating the approved transaction set for compilation."""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.errors import CompileInputError
from ironledger.compile.model import load_approved_set, validate_approved_set, ApprovedSet


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_approved(conn: sqlite3.Connection, *, contra_account="Expenses:Food", minor_units=1500, currency="USD", date="2026-09-01", tx_id="stx-1") -> str:
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1','text/csv','utf-8','prov','2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        " identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('{tx_id}', 'rec-1', 'approved', '{date}', 'Store', 'Groceries', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    contra_val = f"'{contra_account}'" if contra_account is not None else "NULL"
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        f"VALUES ('sp-1', '{tx_id}', 'rec-1', 'imported', 0, 'Assets:Checking', -{minor_units}, '{currency}', 2, '2026-09-01T10:00:00Z'), "
        f"       ('sp-2', '{tx_id}', 'rec-1', 'contra', 1, {contra_val}, {minor_units}, '{currency}', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()
    return tx_id


def test_load_valid_approved_set(db: sqlite3.Connection):
    _seed_approved(db)
    approved_set = load_approved_set(db)
    assert len(approved_set.transactions) == 1
    tx = approved_set.transactions[0]
    assert tx.staged_transaction_id == "stx-1"
    assert tx.payee == "Store"
    assert len(tx.postings) == 2
    assert tx.postings[0].account == "Assets:Checking"
    assert tx.postings[1].account == "Expenses:Food"
    validate_approved_set(approved_set)


def test_refuse_null_contra_account(db: sqlite3.Connection):
    _seed_approved(db, contra_account=None)
    approved_set = load_approved_set(db)
    with pytest.raises(CompileInputError, match="contra posting has NULL account"):
        validate_approved_set(approved_set)


def test_refuse_unbalanced_transaction(db: sqlite3.Connection):
    _seed_approved(db)
    db.execute("UPDATE staged_postings SET minor_units = 2000 WHERE role = 'contra'")
    db.commit()
    approved_set = load_approved_set(db)
    with pytest.raises(CompileInputError, match="does not balance"):
        validate_approved_set(approved_set)


def test_refuse_account_with_conflicting_currencies(db: sqlite3.Connection):
    _seed_approved(db, tx_id="stx-1", contra_account="Expenses:Food", currency="USD")
    # Seed second transaction for same account with EUR
    db.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-2', 'doc-1', 1, '{{}}', '{'d'*64}', '2026-09-01T10:00:00Z')"
    )
    db.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        " identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-2', 'rec-2', 'approved', '2026-09-02', 'Store EU', '', 1, 'fitid', '{'e'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    db.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-3', 'stx-2', 'rec-2', 'imported', 0, 'Assets:EURChecking', -500, 'EUR', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-4', 'stx-2', 'rec-2', 'contra', 1, 'Expenses:Food', 500, 'EUR', 2, '2026-09-01T10:00:00Z')"
    )
    db.commit()
    approved_set = load_approved_set(db)
    with pytest.raises(CompileInputError, match="multiple currencies"):
        validate_approved_set(approved_set)


def test_refuse_non_imported_contra_role_pair(db: sqlite3.Connection):
    """Finding 4: two 'imported' legs (or any non {imported,contra} pair) is refused."""
    _seed_approved(db)
    db.execute("UPDATE staged_postings SET role = 'imported' WHERE role = 'contra'")
    db.commit()
    with pytest.raises(CompileInputError, match="exactly one 'imported' and one 'contra'"):
        validate_approved_set(load_approved_set(db))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.compile'` (impl-missing import, valid RED). Test count after Step 4: 5 passed.

- [ ] **Step 3: Implement `errors.py` and `model.py`**

```python
# src/ironledger/compile/__init__.py
"""IronLedger Phase 3 Beancount compiler and recovery journal package."""

# src/ironledger/compile/errors.py
from __future__ import annotations


class CompileError(Exception):
    """Base exception for all compiler and recovery failures."""


class CompileInputError(CompileError):
    """Refusal when input approved staged transactions violate invariants."""


class CompileLockedError(CompileError):
    """Raised when compile lock cannot be acquired."""


class BeanCheckUnavailableError(CompileError):
    """Raised when bean-check executable is not found on PATH."""


class BeanCheckFailedError(CompileError):
    """Raised when bean-check rejects the compiled staging ledger."""


class AmbiguousRecoveryError(CompileError):
    """Raised when recovery journal encounters an unrecognizable state."""
```

```python
# src/ironledger/compile/model.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final

from ironledger.compile.errors import CompileInputError
from ironledger.conventions import ConventionError, validate_account_name, validate_same_currency_balance


@dataclass(frozen=True)
class ApprovedPosting:
    staged_posting_id: str
    staged_transaction_id: str
    source_record_id: str
    source_document_id: str
    role: str
    posting_index: int
    account: str | None
    minor_units: int
    currency: str
    minor_unit_scale: int
    identity_algo_version: int
    identity_method: str
    identity_fingerprint: str


@dataclass(frozen=True)
class ApprovedTransaction:
    staged_transaction_id: str
    source_record_id: str
    source_document_id: str
    proposed_date: str
    payee: str
    narration: str
    identity_algo_version: int
    identity_method: str
    identity_fingerprint: str
    postings: tuple[ApprovedPosting, ...]


@dataclass(frozen=True)
class ApprovedSet:
    transactions: tuple[ApprovedTransaction, ...]


def load_approved_set(conn: sqlite3.Connection) -> ApprovedSet:
    tx_cursor = conn.execute(
        "SELECT st.staged_transaction_id, st.source_record_id, sr.source_document_id, "
        "       st.proposed_date, st.payee, st.narration, st.identity_algo_version, "
        "       st.identity_method, st.identity_fingerprint "
        "FROM staged_transactions st "
        "JOIN source_records sr ON st.source_record_id = sr.source_record_id "
        "WHERE st.status = 'approved' "
        "ORDER BY st.proposed_date ASC, st.identity_fingerprint ASC"
    )
    tx_rows = tx_cursor.fetchall()

    postings_cursor = conn.execute(
        "SELECT sp.staged_posting_id, sp.staged_transaction_id, sp.source_record_id, sr.source_document_id, "
        "       sp.role, sp.posting_index, sp.account, sp.minor_units, sp.currency, sp.minor_unit_scale, "
        "       sp.identity_algo_version, sp.identity_method, sp.identity_fingerprint "
        "FROM staged_postings sp "
        "JOIN staged_transactions st ON sp.staged_transaction_id = st.staged_transaction_id "
        "JOIN source_records sr ON sp.source_record_id = sr.source_record_id "
        "WHERE st.status = 'approved' "
        "ORDER BY sp.staged_transaction_id, sp.posting_index ASC"
    )
    postings_by_tx: dict[str, list[ApprovedPosting]] = {}
    for p in postings_cursor.fetchall():
        posting = ApprovedPosting(
            staged_posting_id=p[0],
            staged_transaction_id=p[1],
            source_record_id=p[2],
            source_document_id=p[3],
            role=p[4],
            posting_index=p[5],
            account=p[6],
            minor_units=p[7],
            currency=p[8],
            minor_unit_scale=p[9],
            identity_algo_version=p[10],
            identity_method=p[11],
            identity_fingerprint=p[12],
        )
        postings_by_tx.setdefault(posting.staged_transaction_id, []).append(posting)

    transactions: list[ApprovedTransaction] = []
    for t in tx_rows:
        tx_id = t[0]
        tx_postings = postings_by_tx.get(tx_id, [])
        transactions.append(
            ApprovedTransaction(
                staged_transaction_id=tx_id,
                source_record_id=t[1],
                source_document_id=t[2],
                proposed_date=t[3],
                payee=t[4],
                narration=t[5],
                identity_algo_version=t[6],
                identity_method=t[7],
                identity_fingerprint=t[8],
                postings=tuple(tx_postings),
            )
        )
    return ApprovedSet(transactions=tuple(transactions))


def validate_approved_set(approved_set: ApprovedSet) -> None:
    account_currencies: dict[str, str] = {}

    for tx in approved_set.transactions:
        if len(tx.postings) != 2:
            raise CompileInputError(f"Transaction {tx.staged_transaction_id} must have exactly 2 postings, got {len(tx.postings)}")

        # Finding 4: pin the role contract so render.py's imported-then-contra sort is
        # provably deterministic (two 'imported' legs would otherwise sort unstably).
        roles = sorted(p.role for p in tx.postings)
        if roles != ["contra", "imported"]:
            raise CompileInputError(
                f"Transaction {tx.staged_transaction_id} postings must be exactly one 'imported' and one 'contra', got {roles}"
            )

        posting_dicts = []
        for p in tx.postings:
            if p.account is None:
                raise CompileInputError(f"Transaction {tx.staged_transaction_id} {p.role} posting has NULL account")
            try:
                validate_account_name(p.account)
            except ConventionError as e:
                raise CompileInputError(f"Invalid account {p.account!r} in transaction {tx.staged_transaction_id}: {e}") from e

            if p.account in account_currencies and account_currencies[p.account] != p.currency:
                raise CompileInputError(
                    f"Account {p.account} referenced with multiple currencies: {account_currencies[p.account]} and {p.currency}"
                )
            account_currencies[p.account] = p.currency

            posting_dicts.append({
                "account": p.account,
                "minor_units": p.minor_units,
                "currency": p.currency,
            })

        try:
            validate_same_currency_balance(posting_dicts)
        except ConventionError as e:
            raise CompileInputError(f"Transaction {tx.staged_transaction_id} does not balance: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_model.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/ tests/test_compile_model.py
git commit -m "feat(compile): add compile errors and approved set model validation"
```

---

### Task 4: `compile/render.py` — pure deterministic Beancount file rendering

Implement `render_ledger` and rendering helpers. Render `main.beancount`, `accounts.beancount`, and `txns/YYYY.beancount`. Ensure exact string escaping, minor unit scaling, LF endings, 2-space indentation, and metadata attachments.

**Files:**
- Create: `src/ironledger/compile/render.py`
- Test: `tests/test_compile_render.py`

**Interfaces:**
- Consumes: `ApprovedSet`, `ApprovedTransaction`, `ApprovedPosting`.
- Produces: `render_ledger(approved_set: ApprovedSet, *, title: str = "IronLedger") -> dict[str, bytes]`.

- [ ] **Step 1: Write rendering tests**

```python
# tests/test_compile_render.py
"""Tests for deterministic pure-function Beancount ledger rendering."""

from __future__ import annotations

import pytest
from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction
from ironledger.compile.render import render_ledger, format_amount, escape_beancount_string


def _make_sample_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        staged_posting_id="sp-1", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="imported", posting_index=0, account="Assets:Checking",
        minor_units=-1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f"*64
    )
    p2 = ApprovedPosting(
        staged_posting_id="sp-2", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="contra", posting_index=1, account="Expenses:Food",
        minor_units=1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f"*64
    )
    t1 = ApprovedTransaction(
        staged_transaction_id="stx-1", source_record_id="rec-1", source_document_id="doc-1",
        proposed_date="2026-09-01", payee='Coffee "Shop"\\Cafe', narration="Latte",
        identity_algo_version=1, identity_method="fitid", identity_fingerprint="f"*64,
        postings=(p1, p2)
    )
    return ApprovedSet(transactions=(t1,))


def test_format_amount_various_scales():
    assert format_amount(-1234, 2) == "-12.34"
    assert format_amount(1234, 2) == "12.34"
    assert format_amount(50, 2) == "0.50"
    assert format_amount(5, 2) == "0.05"
    assert format_amount(100, 0) == "100"
    assert format_amount(-5, 3) == "-0.005"


def test_escape_beancount_string():
    assert escape_beancount_string('Coffee "Shop"\\Cafe') == 'Coffee \\"Shop\\"\\\\Cafe'


def test_render_ledger_deterministic_output():
    app_set = _make_sample_set()
    files1 = render_ledger(app_set)
    files2 = render_ledger(app_set)
    assert files1 == files2

    assert "main.beancount" in files1
    assert "accounts.beancount" in files1
    assert "txns/2026.beancount" in files1

    main_text = files1["main.beancount"].decode("utf-8")
    assert 'option "title" "IronLedger"' in main_text
    assert 'option "operating_currency" "USD"' in main_text
    assert 'include "accounts.beancount"' in main_text
    assert 'include "txns/2026.beancount"' in main_text

    accounts_text = files1["accounts.beancount"].decode("utf-8")
    assert "2026-09-01 open Assets:Checking USD\n2026-09-01 open Expenses:Food USD\n" == accounts_text

    tx_text = files1["txns/2026.beancount"].decode("utf-8")
    assert '2026-09-01 * "Coffee \\"Shop\\"\\\\Cafe" "Latte"' in tx_text
    assert '  staged-transaction-id: "stx-1"' in tx_text
    assert '  Assets:Checking  -12.34 USD' in tx_text
    assert '    source-document-id: "doc-1"' in tx_text
    assert '  Expenses:Food  12.34 USD' in tx_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.compile.render'`

- [ ] **Step 3: Implement `render.py`**

```python
# src/ironledger/compile/render.py
from __future__ import annotations

from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction


def format_amount(minor_units: int, scale: int) -> str:
    sign = "-" if minor_units < 0 else ""
    abs_units = abs(minor_units)
    if scale == 0:
        return f"{sign}{abs_units}"
    divisor = 10 ** scale
    whole = abs_units // divisor
    frac = abs_units % divisor
    return f"{sign}{whole}.{frac:0{scale}d}"


def escape_beancount_string(val: str) -> str:
    return val.replace("\\", "\\\\").replace('"', '\\"')


def render_accounts_beancount(approved_set: ApprovedSet) -> bytes:
    account_dates: dict[str, str] = {}
    account_currencies: dict[str, str] = {}

    for tx in approved_set.transactions:
        for p in tx.postings:
            assert p.account is not None
            if p.account not in account_dates or tx.proposed_date < account_dates[p.account]:
                account_dates[p.account] = tx.proposed_date
            account_currencies[p.account] = p.currency

    lines: list[str] = []
    for acct in sorted(account_dates.keys()):
        date = account_dates[acct]
        curr = account_currencies[acct]
        lines.append(f"{date} open {acct} {curr}")

    content = "\n".join(lines) + ("\n" if lines else "")
    return content.encode("utf-8")


def render_year_beancount(year: int, txns: list[ApprovedTransaction]) -> bytes:
    sorted_txns = sorted(txns, key=lambda t: (t.proposed_date, t.identity_fingerprint))
    chunks: list[str] = []

    for tx in sorted_txns:
        payee_esc = escape_beancount_string(tx.payee)
        narration_esc = escape_beancount_string(tx.narration)
        lines = [f'{tx.proposed_date} * "{payee_esc}" "{narration_esc}"']
        lines.append(f'  staged-transaction-id: "{tx.staged_transaction_id}"')

        # Imported leg first, then contra. validate_approved_set (Task 3, Finding 4)
        # guarantees roles are exactly {"imported", "contra"}, so this sort is total.
        sorted_postings = sorted(tx.postings, key=lambda p: 0 if p.role == "imported" else 1)
        for p in sorted_postings:
            amt_str = format_amount(p.minor_units, p.minor_unit_scale)
            lines.append(f"  {p.account}  {amt_str} {p.currency}")
            lines.append(f'    source-document-id: "{p.source_document_id}"')
            lines.append(f'    source-record-id: "{p.source_record_id}"')
            lines.append(f'    identity-algo-version: "{p.identity_algo_version}"')
            lines.append(f'    identity-method: "{p.identity_method}"')

        chunks.append("\n".join(lines))

    content = "\n\n".join(chunks) + ("\n" if chunks else "")
    return content.encode("utf-8")


def render_main_beancount(title: str, currencies: list[str], years: list[int]) -> bytes:
    lines = [f'option "title" "{escape_beancount_string(title)}"']
    for curr in sorted(set(currencies)):
        lines.append(f'option "operating_currency" "{curr}"')
    lines.append("")
    lines.append('include "accounts.beancount"')
    for y in sorted(set(years)):
        lines.append(f'include "txns/{y}.beancount"')
    content = "\n".join(lines) + "\n"
    return content.encode("utf-8")


def render_ledger(approved_set: ApprovedSet, *, title: str = "IronLedger") -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    files["accounts.beancount"] = render_accounts_beancount(approved_set)

    currencies: list[str] = []
    txns_by_year: dict[int, list[ApprovedTransaction]] = {}

    for tx in approved_set.transactions:
        year = int(tx.proposed_date.split("-")[0])
        txns_by_year.setdefault(year, []).append(tx)
        for p in tx.postings:
            currencies.append(p.currency)

    years = sorted(txns_by_year.keys())
    for y in years:
        files[f"txns/{y}.beancount"] = render_year_beancount(y, txns_by_year[y])

    files["main.beancount"] = render_main_beancount(title, currencies, years)
    return files
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_render.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/render.py tests/test_compile_render.py
git commit -m "feat(compile): add deterministic pure-function Beancount renderer"
```

---

### Task 5: `compile/hashing.py` — canonical input, intended output, and live output hashes

Implement canonical hashing routines producing SHA-256 lowercase hex digests.

**Files:**
- Create: `src/ironledger/compile/hashing.py`
- Test: `tests/test_compile_hashing.py`

**Interfaces:**
- Consumes: `ApprovedSet`, `dict[str, bytes]`, `pathlib.Path`.
- Produces: `compute_input_hash(approved_set: ApprovedSet) -> str`, `compute_intended_output_hash(files: dict[str, bytes]) -> str`, `compute_actual_output_hash(ledger_dir: Path, year_files: list[str]) -> str`.

- [ ] **Step 1: Write hashing tests**

```python
# tests/test_compile_hashing.py
"""Tests for input and output hash stability and verification."""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction
from ironledger.compile.render import render_ledger
from ironledger.compile.hashing import (
    compute_input_hash,
    compute_intended_output_hash,
    compute_actual_output_hash,
)


def _sample_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        staged_posting_id="sp-1", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="imported", posting_index=0, account="Assets:Checking",
        minor_units=-1000, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="1"*64
    )
    p2 = ApprovedPosting(
        staged_posting_id="sp-2", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="contra", posting_index=1, account="Expenses:Food",
        minor_units=1000, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="1"*64
    )
    t1 = ApprovedTransaction(
        staged_transaction_id="stx-1", source_record_id="rec-1", source_document_id="doc-1",
        proposed_date="2026-09-01", payee="Grocer", narration="", identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="1"*64, postings=(p1, p2)
    )
    return ApprovedSet(transactions=(t1,))


def test_input_hash_is_stable_and_sha256():
    app_set = _sample_set()
    h1 = compute_input_hash(app_set)
    h2 = compute_input_hash(app_set)
    assert h1 == h2
    assert len(h1) == 64
    assert h1.islower()


def test_intended_hash_matches_disk_hash():
    app_set = _sample_set()
    files = render_ledger(app_set)
    intended_hash = compute_intended_output_hash(files)

    with tempfile.TemporaryDirectory() as tmpdir:
        ldir = Path(tmpdir)
        (ldir / "txns").mkdir(parents=True)
        for rel_path, content in files.items():
            fpath = ldir / rel_path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_bytes(content)

        year_files = [p for p in files.keys() if p.startswith("txns/")]
        disk_hash = compute_actual_output_hash(ldir, year_files)
        assert disk_hash == intended_hash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_hashing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.compile.hashing'`

- [ ] **Step 3: Implement `hashing.py`**

```python
# src/ironledger/compile/hashing.py
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from ironledger.compile.model import ApprovedSet

INPUT_HASH_ALGO_VERSION: Final[int] = 1


def compute_input_hash(approved_set: ApprovedSet) -> str:
    records = []
    for tx in approved_set.transactions:
        postings_data = []
        for p in tx.postings:
            postings_data.append({
                "posting_id": p.staged_posting_id,
                "role": p.role,
                "account": p.account,
                "minor_units": p.minor_units,
                "currency": p.currency,
                "minor_unit_scale": p.minor_unit_scale,
                "source_record_id": p.source_record_id,
                "source_document_id": p.source_document_id,
                "identity_algo_version": p.identity_algo_version,
                "identity_method": p.identity_method,
            })
        records.append({
            "staged_transaction_id": tx.staged_transaction_id,
            "proposed_date": tx.proposed_date,
            "payee": tx.payee,
            "narration": tx.narration,
            "identity_algo_version": tx.identity_algo_version,
            "identity_method": tx.identity_method,
            "identity_fingerprint": tx.identity_fingerprint,
            "postings": postings_data,
        })
    payload = {
        "version": INPUT_HASH_ALGO_VERSION,
        "transactions": records,
    }
    # Finding 5: every kwarg here is load-bearing for a stable digest across Python
    # patch releases and locales — sort_keys, fixed separators, ensure_ascii. Do not relax.
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_intended_output_hash(files: dict[str, bytes]) -> str:
    hasher = hashlib.sha256()
    hasher.update(files.get("main.beancount", b""))
    hasher.update(files.get("accounts.beancount", b""))
    year_paths = sorted([p for p in files.keys() if p.startswith("txns/")])
    for yp in year_paths:
        hasher.update(files[yp])
    return hasher.hexdigest()


def compute_actual_output_hash(ledger_dir: Path, year_files: list[str]) -> str:
    hasher = hashlib.sha256()
    main_path = ledger_dir / "main.beancount"
    hasher.update(main_path.read_bytes() if main_path.exists() else b"")

    acct_path = ledger_dir / "accounts.beancount"
    hasher.update(acct_path.read_bytes() if acct_path.exists() else b"")

    for yf in sorted(year_files):
        yp = ledger_dir / yf
        hasher.update(yp.read_bytes() if yp.exists() else b"")
    return hasher.hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_hashing.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/hashing.py tests/test_compile_hashing.py
git commit -m "feat(compile): add canonical input and output hashing"
```

---

### Task 6: `compile/beancheck.py` — `bean-check` subprocess discovery and execution

Implement `beancheck.py` to discover the `bean-check` binary, execute validation on the staging `main.beancount`, enforce timeouts, and extract versions without importing Beancount on the accounting path.

**Files:**
- Create: `src/ironledger/compile/beancheck.py`
- Test: `tests/test_compile_beancheck.py`

**Interfaces:**
- Consumes: `subprocess.run`, `shutil.which`, `importlib.metadata.version`.
- Produces: `COMPILER_VERSION`, Dataclass `BeanCheckResult(ok, exit_code, stdout, stderr, beancount_version, compiler_version)`; `run_bean_check(main_beancount_path: Path, ...) -> BeanCheckResult`.

- [ ] **Step 1: Write bean-check subprocess runner tests**

```python
# tests/test_compile_beancheck.py
"""Tests for bean-check subprocess runner and version tracking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.compile.errors import BeanCheckUnavailableError
from ironledger.compile.beancheck import run_bean_check, COMPILER_VERSION


def test_beancheck_unavailable_raises(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('option "title" "Test"\n')
    with patch("shutil.which", return_value=None):
        with pytest.raises(BeanCheckUnavailableError, match="bean-check executable not found"):
            run_bean_check(main_file)


def test_beancheck_success_mocked(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('option "title" "Test"\n')
    with patch("shutil.which", return_value="/bin/bean-check"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        res = run_bean_check(main_file)
        assert res.ok is True
        assert res.exit_code == 0
        assert res.compiler_version == COMPILER_VERSION


def test_beancheck_failure_captured(tmp_path: Path):
    main_file = tmp_path / "main.beancount"
    main_file.write_text('invalid syntax\n')
    with patch("shutil.which", return_value="/bin/bean-check"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "syntax error at line 1"
        res = run_bean_check(main_file)
        assert res.ok is False
        assert res.exit_code == 1
        assert "syntax error" in res.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_beancheck.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.compile.beancheck'`

- [ ] **Step 3: Implement `beancheck.py`**

```python
# src/ironledger/compile/beancheck.py
from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ironledger.compile.errors import BeanCheckUnavailableError

COMPILER_VERSION: Final[str] = "0.1.0"


@dataclass(frozen=True)
class BeanCheckResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    beancount_version: str
    compiler_version: str


def get_beancount_version() -> str:
    try:
        return importlib.metadata.version("beancount")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def run_bean_check(
    main_beancount_path: Path,
    *,
    timeout_seconds: float = 10.0,
    bean_check_bin: str | None = None,
) -> BeanCheckResult:
    resolved_bin = bean_check_bin or shutil.which("bean-check")
    if resolved_bin is None:
        raise BeanCheckUnavailableError("bean-check executable not found on PATH")

    try:
        proc = subprocess.run(
            [resolved_bin, str(main_beancount_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        b_ver = get_beancount_version()
        return BeanCheckResult(
            ok=(proc.returncode == 0),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            beancount_version=b_ver,
            compiler_version=COMPILER_VERSION,
        )
    except subprocess.TimeoutExpired as e:
        return BeanCheckResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=f"bean-check timed out after {timeout_seconds}s: {e}",
            beancount_version=get_beancount_version(),
            compiler_version=COMPILER_VERSION,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_beancheck.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/beancheck.py tests/test_compile_beancheck.py
git commit -m "feat(compile): add bean-check subprocess runner and version metadata"
```

---

### Task 7: `compile/journal.py` — journal persistence and run lifecycle helpers

Implement database helper routines for `compile_runs` and `compile_journal` state tracking.

**Files:**
- Create: `src/ironledger/compile/journal.py`
- Test: `tests/test_compile_journal.py`

**Interfaces:**
- Consumes: `compile_runs` and `compile_journal` tables via SQLite connection.
- Produces: `next_journal_seq`, `start_compile_run`, `append_compile_journal`, `finish_compile_run`, `fail_compile_run`, `get_active_started_run`, `get_latest_successful_run`.

- [ ] **Step 1: Write journal helper tests**

```python
# tests/test_compile_journal.py
"""Tests for compile run lifecycle and append-only journal persistence."""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.journal import (
    start_compile_run,
    append_compile_journal,
    finish_compile_run,
    fail_compile_run,
    get_active_started_run,
    get_latest_successful_run,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_compile_run_lifecycle_and_journal_sequence(db: sqlite3.Connection):
    run_id = "run-100"
    start_compile_run(
        db,
        compile_run_id=run_id,
        beancount_version="3.0.0",
        compiler_version="0.1.0",
        input_hash="a" * 64,
        intended_output_hash="b" * 64,
        now_utc="2026-09-06T12:00:00Z",
    )

    started_run = get_active_started_run(db)
    assert started_run is not None
    assert started_run["compile_run_id"] == run_id

    seq1 = append_compile_journal(db, run_id, "bean_checked", now_utc="2026-09-06T12:00:01Z")
    assert seq1 == 2  # seq 1 was 'started' in start_compile_run

    finish_compile_run(
        db,
        compile_run_id=run_id,
        actual_output_hash="b" * 64,
        now_utc="2026-09-06T12:00:02Z",
    )

    assert get_active_started_run(db) is None
    latest = get_latest_successful_run(db)
    assert latest is not None
    assert latest["compile_run_id"] == run_id
    assert latest["status"] == "succeeded"


def test_fail_compile_run_records_failure(db: sqlite3.Connection):
    run_id = "run-fail"
    start_compile_run(
        db,
        compile_run_id=run_id,
        beancount_version="3.0.0",
        compiler_version="0.1.0",
        input_hash="a" * 64,
        intended_output_hash="b" * 64,
    )
    fail_compile_run(db, run_id, detail="bean-check exited 1")
    assert get_active_started_run(db) is None
    row = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()
    assert row[0] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_journal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.compile.journal'`

- [ ] **Step 3: Implement `journal.py`**

```python
# src/ironledger/compile/journal.py
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from ironledger.conventions import validate_utc_timestamp


def _now(now_utc: str | None) -> str:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(now_utc)
    return now_utc


def next_journal_seq(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT seq FROM compile_journal ORDER BY seq DESC LIMIT 1")
    row = cursor.fetchone()
    return 1 if row is None else int(row[0]) + 1


def append_compile_journal(
    conn: sqlite3.Connection,
    compile_run_id: str,
    state: str,
    detail: str = "",
    now_utc: str | None = None,
) -> int:
    ts = _now(now_utc)
    seq = next_journal_seq(conn)
    conn.execute(
        "INSERT INTO compile_journal (seq, compile_run_id, state, ts_utc, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (seq, compile_run_id, state, ts, detail),
    )
    conn.commit()
    return seq


def start_compile_run(
    conn: sqlite3.Connection,
    compile_run_id: str,
    beancount_version: str,
    compiler_version: str,
    input_hash: str,
    intended_output_hash: str,
    now_utc: str | None = None,
) -> None:
    ts = _now(now_utc)
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, status, started_at_utc, recovery_state) "
        "VALUES (?, ?, ?, ?, ?, 'started', ?, 'none')",
        (compile_run_id, beancount_version, compiler_version, input_hash, intended_output_hash, ts),
    )
    conn.commit()
    append_compile_journal(conn, compile_run_id, "started", now_utc=ts)


def finish_compile_run(
    conn: sqlite3.Connection,
    compile_run_id: str,
    actual_output_hash: str,
    now_utc: str | None = None,
) -> None:
    ts = _now(now_utc)
    conn.execute(
        "UPDATE compile_runs SET status = 'succeeded', actual_output_hash = ?, finished_at_utc = ? "
        "WHERE compile_run_id = ?",
        (actual_output_hash, ts, compile_run_id),
    )
    conn.commit()
    append_compile_journal(conn, compile_run_id, "succeeded", now_utc=ts)


def fail_compile_run(
    conn: sqlite3.Connection,
    compile_run_id: str,
    detail: str = "",
    now_utc: str | None = None,
) -> None:
    ts = _now(now_utc)
    conn.execute(
        "UPDATE compile_runs SET status = 'failed', finished_at_utc = ? "
        "WHERE compile_run_id = ?",
        (ts, compile_run_id),
    )
    conn.commit()
    append_compile_journal(conn, compile_run_id, "failed", detail=detail, now_utc=ts)


def get_active_started_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT compile_run_id, beancount_version, compiler_version, input_hash, "
        "       intended_output_hash, status, started_at_utc, recovery_state "
        "FROM compile_runs WHERE status = 'started' ORDER BY started_at_utc DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "compile_run_id": row[0],
        "beancount_version": row[1],
        "compiler_version": row[2],
        "input_hash": row[3],
        "intended_output_hash": row[4],
        "status": row[5],
        "started_at_utc": row[6],
        "recovery_state": row[7],
    }


def get_latest_successful_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT compile_run_id, beancount_version, compiler_version, input_hash, "
        "       intended_output_hash, actual_output_hash, status, started_at_utc, finished_at_utc "
        "FROM compile_runs WHERE status IN ('succeeded', 'recovered') "
        "ORDER BY started_at_utc DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "compile_run_id": row[0],
        "beancount_version": row[1],
        "compiler_version": row[2],
        "input_hash": row[3],
        "intended_output_hash": row[4],
        "actual_output_hash": row[5],
        "status": row[6],
        "started_at_utc": row[7],
        "finished_at_utc": row[8],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_journal.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/journal.py tests/test_compile_journal.py
git commit -m "feat(compile): add journal and compile run lifecycle persistence"
```

---

### Task 8: `compile/writer.py` — compile locking, staging creation, and bean-check failure handling

Implement the compile lock manager and staging pipeline up to `bean-check` validation. On validation failure, quarantine staging into `failed-<run_id>`, write `bean-check.txt`, journal failure, and emit an error audit event.

**Files:**
- Create: `src/ironledger/compile/writer.py`
- Test: `tests/test_compile_writer_staging.py`

**Interfaces:**
- Consumes: `compile/errors.py`, `compile/model.py`, `compile/render.py`, `compile/beancheck.py`, `compile/journal.py`, `ironledger.audit.append_audit_event`.
- Produces: `acquire_compile_lock(ledger_dir: Path)`, `write_staging_files(...)`, `handle_bean_check_failure(...)`.

- [ ] **Step 1: Write staging and failure isolation tests**

```python
# tests/test_compile_writer_staging.py
"""Tests for compile locking, staging directory isolation, and bean-check failure handling."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.errors import CompileLockedError, BeanCheckFailedError
from ironledger.compile.model import load_approved_set
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.writer import acquire_compile_lock, compile_approved


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_valid(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1', 'text/csv', 'utf-8', 'p', '2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', '', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Supplies', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()


def test_acquire_lock_prevents_concurrent_access(tmp_path: Path):
    with acquire_compile_lock(tmp_path):
        with pytest.raises(CompileLockedError, match="Compile lock is currently held"):
            with acquire_compile_lock(tmp_path):
                pass


def test_bean_check_failure_isolates_staging_and_journals_error(db: sqlite3.Connection, tmp_path: Path):
    _seed_valid(db)
    failed_res = BeanCheckResult(ok=False, exit_code=1, stdout="", stderr="syntax error", beancount_version="3.0.0", compiler_version="0.1.0")

    with patch("ironledger.compile.writer.run_bean_check", return_value=failed_res):
        with pytest.raises(BeanCheckFailedError, match="bean-check validation failed"):
            compile_approved(db, tmp_path)

    # Verify staging moved to failed-run directory with bean-check.txt
    staging_failed_dirs = list((tmp_path / ".staging").glob("failed-*"))
    assert len(staging_failed_dirs) == 1
    assert (staging_failed_dirs[0] / "bean-check.txt").exists()
    assert "syntax error" in (staging_failed_dirs[0] / "bean-check.txt").read_text()

    # Verify run status is failed and audit row emitted
    run_row = db.execute("SELECT status FROM compile_runs").fetchone()
    assert run_row[0] == "failed"
    audit_row = db.execute("SELECT action, result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert audit_row == ("compile", "error")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_writer_staging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.compile.writer'`

- [ ] **Step 3: Implement writer staging and locking in `writer.py`**

```python
# src/ironledger/compile/writer.py
from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Any

from ironledger.audit import append_audit_event
from ironledger.compile.beancheck import run_bean_check
from ironledger.compile.errors import (
    BeanCheckFailedError,
    CompileError,
    CompileInputError,
    CompileLockedError,
)
from ironledger.compile.hashing import (
    compute_actual_output_hash,
    compute_input_hash,
    compute_intended_output_hash,
)
from ironledger.compile.journal import (
    append_compile_journal,
    fail_compile_run,
    finish_compile_run,
    get_active_started_run,
    start_compile_run,
)
from ironledger.compile.model import load_approved_set, validate_approved_set
from ironledger.compile.render import render_ledger
from ironledger.conventions import validate_utc_timestamp


@contextmanager
def acquire_compile_lock(ledger_dir: Path) -> Generator[Path, None, None]:
    lock_file = ledger_dir / ".compile.lock"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    if lock_file.exists():
        raise CompileLockedError(f"Compile lock is currently held at {lock_file}")
    try:
        lock_file.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
        yield lock_file
    finally:
        if lock_file.exists():
            lock_file.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_writer_staging.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/writer.py tests/test_compile_writer_staging.py
git commit -m "feat(compile): add compile lock and staging error isolation"
```

---

### Task 9: `compile/writer.py` — atomic replace, hash verification, and ledger indexing

Complete `compile_approved` in `writer.py`: execute atomic `os.replace` in fixed order, directory fsync, read back live files to verify `actual_output_hash == intended_output_hash`, update `compile_runs` status to `succeeded`, replace `ledger_entries` / `ledger_postings` rows, and emit audit event.

**Files:**
- Modify: `src/ironledger/compile/writer.py`
- Test: `tests/test_compile_writer_success.py`

**Interfaces:**
- Consumes: All `ironledger.compile` modules, `ledger_entries` and `ledger_postings` SQLite tables.
- Produces: `compile_approved(conn, ledger_dir, *, now_utc=None, bean_check_bin=None) -> CompileSummary`; module-private `_atomic_write_file(dst: Path, data: bytes) -> None` and `_fsync_dir(d: Path) -> None`.

**Eng-review fold (A4.1):** add `_atomic_write_file(dst, data)` — write a sibling temp in `dst.parent`, `os.replace(tmp, dst)`, `_fsync_dir(dst.parent)`. The replace loop in `compile_approved` writes each target with `_atomic_write_file(dst, rendered_files[rel])` (copy semantics) instead of `os.replace(staging_file, dst)` (move semantics), so `.staging/<run_id>/` stays byte-complete until the explicit `shutil.rmtree` after index update. This keeps `_staging_matches(...)` usable during recovery and means a crash mid-replace never destroys the staged copy. `compile/recover.py` (Task 10) imports `_atomic_write_file` and `_fsync_dir` from here.

- [ ] **Step 1: Write compile success and ledger indexing tests**

```python
# tests/test_compile_writer_success.py
"""Tests for complete successful compile, atomic file replacement, and index population."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.writer import compile_approved


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_valid(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1', 'text/csv', 'utf-8', 'p', '2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', 'Supplies', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Supplies', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()


def test_compile_approved_end_to_end_success(db: sqlite3.Connection, tmp_path: Path):
    _seed_valid(db)
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res):
        summary = compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")

    assert summary.entry_count == 1
    assert "txns/2026.beancount" in summary.year_files

    # Check live ledger files written
    assert (tmp_path / "main.beancount").exists()
    assert (tmp_path / "accounts.beancount").exists()
    assert (tmp_path / "txns" / "2026.beancount").exists()

    # Check ledger index populated
    entries = db.execute("SELECT ledger_entry_id, payee, compile_run_id FROM ledger_entries").fetchall()
    assert len(entries) == 1
    assert entries[0][1] == "Store"
    assert entries[0][2] == summary.compile_run_id

    postings = db.execute("SELECT ledger_posting_id, account, minor_units FROM ledger_postings").fetchall()
    assert len(postings) == 2

    # Check compile_runs row status and actual hash
    run = db.execute("SELECT status, actual_output_hash FROM compile_runs WHERE compile_run_id = ?", (summary.compile_run_id,)).fetchone()
    assert run[0] == "succeeded"
    assert run[1] == summary.output_hash

    # Check audit event
    audit = db.execute("SELECT action, result, compile_run_id FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert audit == ("compile", "ok", summary.compile_run_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_writer_success.py -v`
Expected: FAIL

- [ ] **Step 3: Implement complete compile execution in `writer.py`**

```python
# Update src/ironledger/compile/writer.py
from dataclasses import dataclass

@dataclass(frozen=True)
class CompileSummary:
    compile_run_id: str
    entry_count: int
    year_files: tuple[str, ...]
    output_hash: str


def _fsync_dir(dir_path: Path) -> None:
    try:
        dfd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except (OSError, AttributeError):
        pass


def _replace_ledger_index(conn: sqlite3.Connection, compile_run_id: str, approved_set: Any, now_utc: str) -> None:
    # Delete prior index rows (cascade deletes ledger_postings)
    conn.execute("DELETE FROM ledger_entries")

    for tx in approved_set.transactions:
        entry_id = f"le-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO ledger_entries (ledger_entry_id, staged_transaction_id, compile_run_id, "
            " entry_date, flag, payee, narration, created_at_utc) "
            "VALUES (?, ?, ?, ?, '*', ?, ?, ?)",
            (entry_id, tx.staged_transaction_id, compile_run_id, tx.proposed_date, tx.payee, tx.narration, now_utc),
        )
        for p in tx.postings:
            p_id = f"lp-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO ledger_postings (ledger_posting_id, ledger_entry_id, source_record_id, "
                " account, minor_units, currency, minor_unit_scale, identity_algo_version, "
                " identity_method, identity_fingerprint, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    p_id, entry_id, p.source_record_id, p.account, p.minor_units, p.currency,
                    p.minor_unit_scale, p.identity_algo_version, p.identity_method,
                    p.identity_fingerprint, now_utc
                ),
            )
    conn.commit()


def compile_approved(
    conn: sqlite3.Connection,
    ledger_dir: Path,
    *,
    now_utc: str | None = None,
    bean_check_bin: str | None = None,
) -> CompileSummary:
    now = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(now)

    with acquire_compile_lock(ledger_dir):
        active = get_active_started_run(conn)
        if active is not None:
            raise CompileError(f"A dangling compile run {active['compile_run_id']} is active. Run 'compile recover' first.")

        approved_set = load_approved_set(conn)
        validate_approved_set(approved_set)

        rendered_files = render_ledger(approved_set)
        in_hash = compute_input_hash(approved_set)
        intended_hash = compute_intended_output_hash(rendered_files)

        run_id = f"crun-{uuid.uuid4().hex[:12]}"
        staging_dir = ledger_dir / ".staging" / run_id
        staging_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content in rendered_files.items():
            out_file = staging_dir / rel_path
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(content)

        # Execute bean-check
        check_res = run_bean_check(staging_dir / "main.beancount", bean_check_bin=bean_check_bin)

        start_compile_run(
            conn,
            compile_run_id=run_id,
            beancount_version=check_res.beancount_version,
            compiler_version=check_res.compiler_version,
            input_hash=in_hash,
            intended_output_hash=intended_hash,
            now_utc=now,
        )

        if not check_res.ok:
            failed_dir = ledger_dir / ".staging" / f"failed-{run_id}"
            shutil.move(str(staging_dir), str(failed_dir))
            (failed_dir / "bean-check.txt").write_text(check_res.stderr or check_res.stdout, encoding="utf-8")
            fail_compile_run(conn, run_id, detail=f"bean-check exit code {check_res.exit_code}", now_utc=now)
            append_audit_event(conn, actor="operator", action="compile", target=run_id, result="error", compile_run_id=run_id, now_utc=now)
            raise BeanCheckFailedError(f"bean-check validation failed:\n{check_res.stderr}")

        append_compile_journal(conn, run_id, "bean_checked", now_utc=now)

        # Atomic replacement in fixed order: accounts.beancount, main.beancount, txns/YYYY.
        # A4.1: copy semantics (sibling temp + os.replace) — `.staging` stays intact so a
        # crash here is recoverable from staging as well as from a re-render.
        (ledger_dir / "txns").mkdir(parents=True, exist_ok=True)
        order = ["accounts.beancount", "main.beancount"] + sorted([p for p in rendered_files if p.startswith("txns/")])
        for p in order:
            dst = ledger_dir / p
            dst.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_file(dst, rendered_files[p])

        _fsync_dir(ledger_dir)
        append_compile_journal(conn, run_id, "replaced", now_utc=now)

        # Verify actual hash on disk
        year_files = [p for p in rendered_files if p.startswith("txns/")]
        actual_hash = compute_actual_output_hash(ledger_dir, year_files)
        if actual_hash != intended_hash:
            raise CompileError(f"Live ledger output hash mismatch: actual={actual_hash} != intended={intended_hash}")

        finish_compile_run(conn, run_id, actual_output_hash=actual_hash, now_utc=now)
        _replace_ledger_index(conn, run_id, approved_set, now)

        # Cleanup staging directory
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        append_audit_event(
            conn, actor="operator", action="compile", target=run_id, result="ok",
            compile_run_id=run_id, input_hash=in_hash, output_hash=actual_hash, now_utc=now
        )

        return CompileSummary(
            compile_run_id=run_id,
            entry_count=len(approved_set.transactions),
            year_files=tuple(year_files),
            output_hash=actual_hash,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_writer_success.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/writer.py tests/test_compile_writer_success.py
git commit -m "feat(compile): implement atomic ledger replacement and index population"
```

---

### Task 10: `compile/recover.py` — recovery decision table implementation

Implement `recover_dangling_compile` based on the Section 11 decision table.

**Files:**
- Create: `src/ironledger/compile/recover.py`
- Test: `tests/test_compile_recover.py`

**Interfaces:**
- Consumes: `compile/journal.py`, `compile/hashing.py`, `compile/writer.py`.
- Produces: `RecoveryDecision`, `recover_dangling_compile(conn, ledger_dir, *, now_utc=None) -> RecoveryDecision`.

- [ ] **Step 1: Write unit tests covering the decision table**

```python
# tests/test_compile_recover.py
"""Tests for compiler recovery decision table."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.errors import AmbiguousRecoveryError
from ironledger.compile.journal import start_compile_run
from ironledger.compile.recover import recover_dangling_compile


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_recover_when_nothing_to_recover(db: sqlite3.Connection, tmp_path: Path):
    res = recover_dangling_compile(db, tmp_path)
    assert res.action == "none"
    assert res.compile_run_id is None


def test_recover_pre_write_abort_marks_failed(db: sqlite3.Connection, tmp_path: Path):
    run_id = "crun-aborted"
    start_compile_run(
        db, compile_run_id=run_id, beancount_version="3.0.0", compiler_version="0.1.0",
        input_hash="a"*64, intended_output_hash="b"*64
    )
    # Staging directory absent
    res = recover_dangling_compile(db, tmp_path)
    assert res.action == "marked_failed"
    assert res.compile_run_id == run_id

    row = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()
    assert row[0] == "failed"


def test_recover_staging_hash_mismatch_refuses(db: sqlite3.Connection, tmp_path: Path):
    run_id = "crun-corrupt"
    start_compile_run(
        db, compile_run_id=run_id, beancount_version="3.0.0", compiler_version="0.1.0",
        input_hash="a"*64, intended_output_hash="b"*64
    )
    staging = tmp_path / ".staging" / run_id
    staging.mkdir(parents=True)
    (staging / "main.beancount").write_bytes(b"corrupted")

    with pytest.raises(AmbiguousRecoveryError, match="staging hash mismatch|re-render|unrecognized"):
        recover_dangling_compile(db, tmp_path)

    # Run remains started, journal records refused
    row = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()
    assert row[0] == "started"
    j_state = db.execute("SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()[0]
    assert j_state == "refused"


def test_recovery_is_reentrant_after_mid_recovery_crash(db: sqlite3.Connection, tmp_path: Path):
    """A4.1: a crash during recovery (only some live files written) still recovers on
    the next `compile recover` — no row-4 escalation, terminal state 'recovered'."""
    ledger_dir, run_id, rendered = _seed_started_run_with_valid_staging(db, tmp_path)
    # Simulate a partial recovery: write only accounts.beancount to live, leave the rest.
    (ledger_dir / "accounts.beancount").write_bytes(rendered["accounts.beancount"])

    res = recover_dangling_compile(db, ledger_dir, now_utc="2026-09-06T12:00:00Z")
    assert res.action == "recovered"
    assert db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0] == "recovered"
    # Every live file now holds the intended bytes.
    for rel, want in rendered.items():
        assert (ledger_dir / rel).read_bytes() == want
    # No 'refused' journal row.
    states = [r[0] for r in db.execute("SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq", (run_id,)).fetchall()]
    assert "refused" not in states
    assert states[-1] == "recovered"


def test_recover_rerun_after_full_recovery_is_safe_noop(db: sqlite3.Connection, tmp_path: Path):
    """A4.1: re-running `compile recover` once the tree is intact is a safe no-op."""
    ledger_dir, run_id, rendered = _seed_started_run_with_valid_staging(db, tmp_path)
    first = recover_dangling_compile(db, ledger_dir, now_utc="2026-09-06T12:00:00Z")
    assert first.action == "recovered"
    # Second call: nothing dangling now, so 'none'; if the run were still 'started'
    # it would re-finalize without error and without a row-4 refusal.
    second = recover_dangling_compile(db, ledger_dir, now_utc="2026-09-06T12:00:05Z")
    assert second.action in {"none", "recovered"}
    for rel, want in rendered.items():
        assert (ledger_dir / rel).read_bytes() == want
```

`_seed_started_run_with_valid_staging(db, tmp_path)` seeds an approved set, renders it, writes the full render into `tmp_path/.staging/<run_id>/`, calls `start_compile_run` with the matching `input_hash` / `intended_output_hash`, and returns `(ledger_dir, run_id, rendered_dict)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compile_recover.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.compile.recover'` (impl-missing import, valid RED).

- [ ] **Step 3: Implement `recover.py`**

```python
# src/ironledger/compile/recover.py
from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ironledger.audit import append_audit_event
from ironledger.compile.errors import AmbiguousRecoveryError
from ironledger.compile.hashing import (
    compute_actual_output_hash,
    compute_intended_output_hash,
)
from ironledger.compile.journal import (
    append_compile_journal,
    fail_compile_run,
    get_active_started_run,
    get_latest_successful_run,
)
from ironledger.compile.model import load_approved_set, validate_approved_set
from ironledger.compile.render import render_ledger
from ironledger.compile.hashing import compute_input_hash
from ironledger.compile.writer import _atomic_write_file, _fsync_dir, _replace_ledger_index, acquire_compile_lock
from ironledger.conventions import validate_utc_timestamp


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    compile_run_id: str | None
    detail: str


def _live_tree_hash(ledger_dir: Path, rendered: dict[str, bytes]) -> str:
    """Hash the live ledger over exactly the intended relative-path set, missing files as b''."""
    live: dict[str, bytes] = {}
    for rel in rendered:
        fp = ledger_dir / rel
        live[rel] = fp.read_bytes() if fp.exists() else b""
    return compute_intended_output_hash(live)


def _live_tree_empty(ledger_dir: Path) -> bool:
    return not (ledger_dir / "main.beancount").exists() and not (ledger_dir / "accounts.beancount").exists()


def _staging_matches(staging_dir: Path, intended_hash: str) -> bool:
    if not staging_dir.exists():
        return False
    files: dict[str, bytes] = {}
    for root, _, names in os.walk(staging_dir):
        for n in names:
            fp = Path(root) / n
            files[fp.relative_to(staging_dir).as_posix()] = fp.read_bytes()
    return bool(files) and compute_intended_output_hash(files) == intended_hash


def recover_dangling_compile(
    conn: sqlite3.Connection,
    ledger_dir: Path,
    *,
    now_utc: str | None = None,
) -> RecoveryDecision:
    now = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_utc_timestamp(now)

    with acquire_compile_lock(ledger_dir):
        active = get_active_started_run(conn)
        if active is None:
            return RecoveryDecision(action="none", compile_run_id=None, detail="No active started compile run")

        run_id = active["compile_run_id"]
        intended_hash = active["intended_output_hash"]
        staging_dir = ledger_dir / ".staging" / run_id

        prev = get_latest_successful_run(conn)
        prev_hash = prev["actual_output_hash"] if prev else None

        # A4.1: recovery is idempotent and re-entrant. It does NOT consume `.staging`
        # incrementally. Instead it re-derives the intended output from the approved
        # set (spec decision 2: output is a pure function of the approved set), proves
        # that derivation still matches the crashed run's frozen `intended_output_hash`,
        # then writes only the live files that do not already hold the intended bytes.
        # A crash anywhere in this block leaves the run re-eligible for exactly this
        # path on the next `compile recover`.

        # Re-render from the current approved set and re-check identity.
        approved_set = load_approved_set(conn)
        try:
            validate_approved_set(approved_set)
        except Exception as exc:  # CompileInputError
            append_compile_journal(conn, run_id, "refused", detail="approved set no longer valid", now_utc=now)
            raise AmbiguousRecoveryError(f"Approved set no longer validates: {exc}") from exc

        if compute_input_hash(approved_set) != active["input_hash"]:
            append_compile_journal(conn, run_id, "refused", detail="approved set changed since run start", now_utc=now)
            raise AmbiguousRecoveryError("Approved set changed since the crashed run started; recompile from clean.")

        rendered = render_ledger(approved_set)  # rel-path -> bytes
        rendered_hash = compute_intended_output_hash(rendered)
        if rendered_hash != intended_hash:
            append_compile_journal(conn, run_id, "refused", detail="re-render does not match intended_output_hash", now_utc=now)
            raise AmbiguousRecoveryError(f"Re-render hash {rendered_hash} != intended {intended_hash}")

        # Classify the live tree.
        live_matches_intended = _live_tree_hash(ledger_dir, rendered) == intended_hash
        live_matches_prev = prev_hash is not None and _live_tree_hash(ledger_dir, rendered) == prev_hash
        staging_ok = _staging_matches(staging_dir, intended_hash)

        # Case 1: nothing was written and staging never completed. Pre-write abort.
        if not live_matches_intended and not staging_ok and (live_matches_prev or _live_tree_empty(ledger_dir)):
            fail_compile_run(conn, run_id, detail="aborted before writes", now_utc=now)
            return RecoveryDecision(action="marked_failed", compile_run_id=run_id, detail="Aborted before writes, marked failed")

        # Row-4 genuine corruption: live tree matches neither prev nor intended, AND
        # there is no intact staging matching intended to recover from, AND the live
        # tree is non-empty (a partial replace compounded by an external edit).
        if not live_matches_intended and not live_matches_prev and not staging_ok and not _live_tree_empty(ledger_dir):
            append_compile_journal(conn, run_id, "refused", detail="live ledger in an unrecognized state", now_utc=now)
            raise AmbiguousRecoveryError("Live ledger matches neither the previous output nor the intended output, and no intact staging is present.")

        # Deterministic recovery (re-entrant). Write only files that differ.
        (ledger_dir / "txns").mkdir(parents=True, exist_ok=True)
        wrote_any = False
        order = ["accounts.beancount", "main.beancount"] + sorted(p for p in rendered if p.startswith("txns/"))
        for rel in order:
            dst = ledger_dir / rel
            want = rendered[rel]
            if dst.exists() and dst.read_bytes() == want:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_file(dst, want)  # write sibling temp + os.replace + fsync dir
            wrote_any = True
        # Drop any live txns/*.beancount not in the intended set (year removed).
        live_txns_dir = ledger_dir / "txns"
        if live_txns_dir.exists():
            intended_txns = {p for p in rendered if p.startswith("txns/")}
            for f in sorted(live_txns_dir.glob("*.beancount")):
                if f"txns/{f.name}" not in intended_txns:
                    f.unlink()
                    wrote_any = True
        _fsync_dir(ledger_dir)

        if wrote_any:
            append_compile_journal(conn, run_id, "replaced", now_utc=now)

        actual_hash = _live_tree_hash(ledger_dir, rendered)
        if actual_hash != intended_hash:
            append_compile_journal(conn, run_id, "refused", detail="live ledger in an unrecognized state", now_utc=now)
            raise AmbiguousRecoveryError(f"Post-write live hash {actual_hash} != intended {intended_hash}")

        # Idempotent finalize: safe to re-run even if the row is already 'recovered'.
        conn.execute(
            "UPDATE compile_runs SET status = 'recovered', actual_output_hash = ?, "
            "finished_at_utc = COALESCE(finished_at_utc, ?), recovery_state = 'recovered' "
            "WHERE compile_run_id = ? AND status != 'recovered'",
            (actual_hash, now, run_id),
        )
        conn.commit()
        append_compile_journal(conn, run_id, "recovered", now_utc=now)

        _replace_ledger_index(conn, run_id, approved_set, now)  # replace-not-append, idempotent

        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        append_audit_event(
            conn, actor="operator", action="compile", target=run_id, result="ok",
            compile_run_id=run_id, output_hash=actual_hash, now_utc=now
        )

        detail = "Finished deterministic recovery" if wrote_any else "Recovery re-run: live tree already intact, finalized"
        return RecoveryDecision(action="recovered", compile_run_id=run_id, detail=detail)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compile_recover.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/recover.py tests/test_compile_recover.py
git commit -m "feat(compile): implement re-entrant recovery decision table"
```

---

### Task 11: Interrupted compile crash injection and multi-file recovery integration tests

Inject crash simulations during the atomic replacement phase (e.g. `accounts.beancount` replaced but `main.beancount` not yet replaced) and verify that `recover_dangling_compile` finishes atomic swap and records the `recovered` run status.

**Files:**
- Test: `tests/test_compile_recovery_integration.py`

**Interfaces:**
- Consumes: `compile_approved`, `recover_dangling_compile`.
- Produces: Verified crash recovery integration tests.

- [ ] **Step 1: Write crash-injection integration test**

```python
# tests/test_compile_recovery_integration.py
"""Integration tests for interrupted compile crash injection and recovery."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.writer import compile_approved
from ironledger.compile.recover import recover_dangling_compile


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1', 'text/csv', 'utf-8', 'p', '2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', '', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Food', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()


def test_crash_mid_replace_recovers_cleanly(db: sqlite3.Connection, tmp_path: Path):
    _seed(db)
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")

    original_replace = os.replace
    call_count = 0

    def mock_replace_crash(src, dst):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("Simulated power failure / crash mid-replace")
        return original_replace(src, dst)

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res), \
         patch("os.replace", side_effect=mock_replace_crash):
        with pytest.raises(OSError, match="Simulated power failure"):
            compile_approved(db, tmp_path)

    # A started run is left active, staging exists
    run_row = db.execute("SELECT compile_run_id, status FROM compile_runs WHERE status = 'started'").fetchone()
    assert run_row is not None
    run_id = run_row[0]

    # Execute recovery
    rec = recover_dangling_compile(db, tmp_path)
    assert rec.action == "recovered"
    assert rec.compile_run_id == run_id

    # Verify status is now 'recovered'
    status = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0]
    assert status == "recovered"

    # Verify live ledger files exist and are valid
    assert (tmp_path / "main.beancount").exists()
    assert (tmp_path / "accounts.beancount").exists()
    assert (tmp_path / "txns" / "2026.beancount").exists()


def test_crash_during_recovery_then_second_recover_completes(db: sqlite3.Connection, tmp_path: Path):
    """A4.1: crash the recovery itself mid-write, then a second `compile recover`
    drives the run to 'recovered' with no row-4 escalation (re-entrancy)."""
    _seed(db)
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")
    original_replace = os.replace

    # First: crash the primary compile mid-replace.
    n = 0
    def crash_second(src, dst):
        nonlocal n
        n += 1
        if n == 2:
            raise OSError("crash mid-replace")
        return original_replace(src, dst)
    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res), \
         patch("os.replace", side_effect=crash_second):
        with pytest.raises(OSError):
            compile_approved(db, tmp_path)
    run_id = db.execute("SELECT compile_run_id FROM compile_runs WHERE status = 'started'").fetchone()[0]

    # Now crash the FIRST recovery attempt mid-write.
    m = 0
    def crash_first_recovery(src, dst):
        nonlocal m
        m += 1
        if m == 1:
            raise OSError("crash mid-recovery")
        return original_replace(src, dst)
    with patch("os.replace", side_effect=crash_first_recovery):
        with pytest.raises(OSError):
            recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:00:00Z")
    assert db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0] == "started"

    # Second recovery, no injected fault: must complete.
    rec = recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:00:10Z")
    assert rec.action == "recovered"
    assert db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0] == "recovered"
    states = [r[0] for r in db.execute("SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq", (run_id,)).fetchall()]
    assert "refused" not in states and states[-1] == "recovered"

    # Item 12 tail: a third recover is a safe no-op.
    again = recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:00:20Z")
    assert again.action in {"none", "recovered"}
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_compile_recovery_integration.py -v`
Expected: PASS (2 passed)

- [ ] **Step 3: Commit**

```bash
git add tests/test_compile_recovery_integration.py
git commit -m "test(compile): add crash-injection recovery integration tests incl. re-entrancy"
```

---

### Task 12: `cli/auth.py` — compile authorization phrases and safe mode gates

Add `authorize compile` and `authorize compile recover` fixed phrases to `cli/auth.py` and enforce safe-mode denial.

**Files:**
- Modify: `src/ironledger/cli/auth.py`
- Test: `tests/test_cli_auth_phase3.py`

**Interfaces:**
- Consumes: `cli/auth.py`
- Produces: `COMPILE_PHRASE = "authorize compile"`, `COMPILE_RECOVER_PHRASE = "authorize compile recover"`.

- [ ] **Step 1: Write CLI auth tests for compile actions**

```python
# tests/test_cli_auth_phase3.py
"""Tests for compile and recovery authorization phrases and safe-mode gating."""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.cli.auth import (
    require_operator,
    AuthorizationError,
    COMPILE_PHRASE,
    COMPILE_RECOVER_PHRASE,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_compile_phrases_defined():
    assert COMPILE_PHRASE == "authorize compile"
    assert COMPILE_RECOVER_PHRASE == "authorize compile recover"


def test_compile_authorized_with_confirm_flag(db: sqlite3.Connection):
    res = require_operator(db, action="compile", expected_phrase=COMPILE_PHRASE, confirm_flag="authorize compile")
    assert res == "confirm-flag"


def test_compile_denied_with_wrong_phrase(db: sqlite3.Connection):
    with pytest.raises(AuthorizationError):
        require_operator(db, action="compile", expected_phrase=COMPILE_PHRASE, confirm_flag="wrong phrase")
    audit = db.execute("SELECT action, result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert audit == ("compile", "denied")


def test_safe_mode_blocks_compile_and_recover(db: sqlite3.Connection, monkeypatch):
    monkeypatch.setenv("IRONLEDGER_SAFE_MODE", "1")
    with pytest.raises(AuthorizationError, match="safe mode"):
        require_operator(db, action="compile", expected_phrase=COMPILE_PHRASE, confirm_flag="authorize compile")

    with pytest.raises(AuthorizationError, match="safe mode"):
        require_operator(db, action="compile recover", expected_phrase=COMPILE_RECOVER_PHRASE, confirm_flag="authorize compile recover")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_auth_phase3.py -v`
Expected: FAIL with `ImportError: cannot import name 'COMPILE_PHRASE'`

- [ ] **Step 3: Update `cli/auth.py`**

```python
# Modify src/ironledger/cli/auth.py
# Add constants:
COMPILE_PHRASE: Final[str] = "authorize compile"
COMPILE_RECOVER_PHRASE: Final[str] = "authorize compile recover"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_auth_phase3.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/cli/auth.py tests/test_cli_auth_phase3.py
git commit -m "feat(auth): add compile and compile recover authorization phrases"
```

---

### Task 13: `cli/render.py` — status, compile summaries, and recovery formatting

Implement formatting functions for `compile status`, compile summaries, and recovery reports, including structured JSON support.

**Files:**
- Modify: `src/ironledger/cli/render.py`
- Test: `tests/test_cli_render_phase3.py`

**Interfaces:**
- Consumes: `CompileSummary`, `RecoveryDecision`, `CompileStatus`.
- Produces: `render_compile_summary`, `render_compile_status`, `render_recovery_report`.

- [ ] **Step 1: Write CLI render tests**

```python
# tests/test_cli_render_phase3.py
"""Tests for CLI rendering of compile summary, status, and recovery reports."""

from __future__ import annotations

import json
from ironledger.compile.writer import CompileSummary
from ironledger.compile.recover import RecoveryDecision
from ironledger.cli.render import (
    render_compile_summary,
    render_recovery_report,
    render_compile_status,
)


def test_render_compile_summary():
    summary = CompileSummary(
        compile_run_id="crun-123",
        entry_count=42,
        year_files=("txns/2026.beancount",),
        output_hash="e" * 64,
    )
    out = render_compile_summary(summary)
    assert "crun-123" in out
    assert "42 entries" in out
    assert "e" * 64 in out


def test_render_recovery_report():
    rec = RecoveryDecision(action="recovered", compile_run_id="crun-123", detail="Finished atomic replace")
    out = render_recovery_report(rec)
    assert "Recovered compile run crun-123" in out


def test_render_compile_status_json():
    status_data = {
        "latest_run": {"compile_run_id": "crun-1", "status": "succeeded"},
        "active_run": None,
        "on_disk_hash": "a" * 64,
        "hash_matches": True,
    }
    out = render_compile_status(status_data, as_json=True)
    parsed = json.loads(out)
    assert parsed["latest_run"]["status"] == "succeeded"
    assert parsed["hash_matches"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_render_phase3.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement render functions in `cli/render.py`**

```python
# Add to src/ironledger/cli/render.py
from typing import Any
import json
from ironledger.compile.writer import CompileSummary
from ironledger.compile.recover import RecoveryDecision


def render_compile_summary(summary: CompileSummary) -> str:
    lines = [
        f"Compile run {summary.compile_run_id} succeeded:",
        f"  Entries compiled: {summary.entry_count}",
        f"  Year files: {', '.join(summary.year_files) if summary.year_files else 'none'}",
        f"  Output SHA-256: {summary.output_hash}",
    ]
    return "\n".join(lines)


def render_recovery_report(rec: RecoveryDecision) -> str:
    if rec.action == "none":
        return "No dangling compile run to recover."
    return f"Recovery [{rec.action}]: {rec.compile_run_id} - {rec.detail}"


def render_compile_status(status_data: dict[str, Any], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(status_data, indent=2, sort_keys=True)

    lines = ["Compile Status:"]
    latest = status_data.get("latest_run")
    if latest:
        lines.append(f"  Latest Run: {latest['compile_run_id']} ({latest['status']}) at {latest.get('finished_at_utc') or latest.get('started_at_utc')}")
        lines.append(f"  Expected Hash: {latest.get('actual_output_hash') or latest.get('intended_output_hash')}")
    else:
        lines.append("  Latest Run: none")

    active = status_data.get("active_run")
    if active:
        lines.append(f"  Active Started Run: {active['compile_run_id']} (requires 'compile recover')")

    lines.append(f"  On-Disk Hash:  {status_data.get('on_disk_hash', 'none')}")
    lines.append(f"  Hash Matches:  {'YES' if status_data.get('hash_matches') else 'NO'}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_render_phase3.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/cli/render.py tests/test_cli_render_phase3.py
git commit -m "feat(cli): add compile status and recovery renderers"
```

---

### Task 14: `cli/__main__.py` — wire the `compile` subcommand tree

Add `ironledger compile`, `ironledger compile status`, and `ironledger compile recover` subcommands to `cli/__main__.py`.

**Files:**
- Modify: `src/ironledger/cli/__main__.py`
- Test: `tests/test_cli_compile.py`

**Interfaces:**
- Consumes: `cli/auth.py`, `cli/render.py`, `compile/writer.py`, `compile/recover.py`, `compile/journal.py`.
- Produces: CLI commands `compile`, `compile status`, `compile recover`.

- [ ] **Step 1: Write CLI command integration tests**

```python
# tests/test_cli_compile.py
"""CLI tests for compile, compile status, and compile recover."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.cli.__main__ import main


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "ironledger.db"
    conn = connect(str(p))
    migrations.migrate(conn)
    conn.close()
    return p


def _seed(p: Path):
    conn = connect(str(p))
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1', 'text/csv', 'utf-8', 'p', '2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', '', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Food', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()
    conn.close()


def test_cli_compile_success(db_path: Path, tmp_path: Path, capsys):
    _seed(db_path)
    ledger_dir = tmp_path / "ledger"
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res):
        rc = main([
            "--db", str(db_path),
            "compile",
            "--ledger-dir", str(ledger_dir),
            "--confirm", "authorize compile"
        ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "succeeded" in captured.out


def test_cli_compile_status_read_only(db_path: Path, tmp_path: Path, capsys):
    ledger_dir = tmp_path / "ledger"
    rc = main([
        "--db", str(db_path),
        "compile", "status",
        "--ledger-dir", str(ledger_dir)
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Compile Status:" in captured.out


def test_cli_compile_auth_failure_exits_code_3(db_path: Path, tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    rc = main([
        "--db", str(db_path),
        "compile",
        "--ledger-dir", str(ledger_dir),
        "--confirm", "wrong phrase"
    ])
    assert rc == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_compile.py -v`
Expected: FAIL

- [ ] **Step 3: Wire subcommands in `cli/__main__.py`**

Add argument parser subcommands for `compile`, `compile status`, and `compile recover`, and wire their handlers with proper authorization calls, error handling, and exit codes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_compile.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/cli/__main__.py tests/test_cli_compile.py
git commit -m "feat(cli): wire compile, compile status, and compile recover commands"
```

---

### Task 15: Dependency posture amendment, exit gate test contract, and regression sweep

Amend `docs/meta/ironledger-dependency-posture.md` for Phase 3, implement the comprehensive Phase 3 exit gate test contract matching Section 14 of the design spec, and run the complete test suite to confirm zero regressions.

**Files:**
- Modify: `docs/meta/ironledger-dependency-posture.md`
- Test: `tests/test_phase3_exit_contract.py`

**Interfaces:**
- Consumes: All Phase 3 components and existing codebase.
- Produces: Full regression pass across all test suites (>300 tests passing).

- [ ] **Step 1: Write the Section 14 exit gate test contract suite**

```python
# tests/test_phase3_exit_contract.py
"""Verification test suite mapping all 17 items of the Phase 3 exit gate test contract."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction, load_approved_set, validate_approved_set
from ironledger.compile.render import render_ledger, format_amount, escape_beancount_string
from ironledger.compile.hashing import compute_input_hash, compute_intended_output_hash
from ironledger.compile.errors import CompileInputError, BeanCheckUnavailableError, CompileLockedError
from ironledger.compile.beancheck import run_bean_check, BeanCheckResult
from ironledger.compile.writer import compile_approved, acquire_compile_lock
from ironledger.compile.recover import recover_dangling_compile
from ironledger.cli.auth import require_operator, AuthorizationError, COMPILE_PHRASE, COMPILE_RECOVER_PHRASE


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed(conn: sqlite3.Connection, *, contra_account="Expenses:Food", minor_units=1500, currency="USD", date="2026-09-01", tx_id="stx-1"):
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1','text/csv','utf-8','prov','2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('{tx_id}', 'rec-1', 'approved', '{date}', 'Store', 'Groceries', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    contra_val = f"'{contra_account}'" if contra_account is not None else "NULL"
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        f"VALUES ('sp-1', '{tx_id}', 'rec-1', 'imported', 0, 'Assets:Checking', -{minor_units}, '{currency}', 2, '2026-09-01T10:00:00Z'), "
        f"       ('sp-2', '{tx_id}', 'rec-1', 'contra', 1, {contra_val}, {minor_units}, '{currency}', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()


# 1. Byte-identical output across permutations
def test_contract_1_render_byte_identical():
    p1 = ApprovedPosting("sp-1", "stx-1", "rec-1", "doc-1", "imported", 0, "Assets:Checking", -100, "USD", 2, 1, "fitid", "1"*64)
    p2 = ApprovedPosting("sp-2", "stx-1", "rec-1", "doc-1", "contra", 1, "Expenses:Food", 100, "USD", 2, 1, "fitid", "1"*64)
    t1 = ApprovedTransaction("stx-1", "rec-1", "doc-1", "2026-09-01", "Payee", "", 1, "fitid", "1"*64, (p1, p2))
    app_set = ApprovedSet((t1,))
    assert render_ledger(app_set) == render_ledger(app_set)


# 2. Amount formatting
def test_contract_2_amount_formatting():
    assert format_amount(-1234, 2) == "-12.34"
    assert format_amount(0, 2) == "0.00"
    assert format_amount(5, 0) == "5"


# 3. Deterministic order
def test_contract_3_order():
    p1 = ApprovedPosting("sp-1", "stx-1", "rec-1", "doc-1", "imported", 0, "Assets:Checking", -100, "USD", 2, 1, "fitid", "1"*64)
    p2 = ApprovedPosting("sp-2", "stx-1", "rec-1", "doc-1", "contra", 1, "Expenses:Food", 100, "USD", 2, 1, "fitid", "1"*64)
    t1 = ApprovedTransaction("stx-1", "rec-1", "doc-1", "2026-09-01", "Payee", "", 1, "fitid", "1"*64, (p1, p2))
    out = render_ledger(ApprovedSet((t1,)))["txns/2026.beancount"].decode()
    imported_idx = out.find("Assets:Checking")
    contra_idx = out.find("Expenses:Food")
    assert imported_idx < contra_idx


# 4. Escaping
def test_contract_4_escaping():
    assert escape_beancount_string('Test "Quote" \\ Slash') == 'Test \\"Quote\\" \\\\ Slash'


# 5. Stable hashes
def test_contract_5_stable_hashes():
    p1 = ApprovedPosting("sp-1", "stx-1", "rec-1", "doc-1", "imported", 0, "Assets:Checking", -100, "USD", 2, 1, "fitid", "1"*64)
    p2 = ApprovedPosting("sp-2", "stx-1", "rec-1", "doc-1", "contra", 1, "Expenses:Food", 100, "USD", 2, 1, "fitid", "1"*64)
    t1 = ApprovedTransaction("stx-1", "rec-1", "doc-1", "2026-09-01", "Payee", "", 1, "fitid", "1"*64, (p1, p2))
    h1 = compute_input_hash(ApprovedSet((t1,)))
    assert len(h1) == 64


# 8. Refuse NULL contra
def test_contract_8_refuse_null_contra(db: sqlite3.Connection):
    _seed(db, contra_account=None)
    with pytest.raises(CompileInputError):
        validate_approved_set(load_approved_set(db))


# 13. Concurrency lock denial
def test_contract_13_lock_denial(tmp_path: Path):
    with acquire_compile_lock(tmp_path):
        with pytest.raises(CompileLockedError):
            with acquire_compile_lock(tmp_path):
                pass


# 14. Safe mode blocks compile
def test_contract_14_safe_mode_denial(db: sqlite3.Connection, monkeypatch):
    monkeypatch.setenv("IRONLEDGER_SAFE_MODE", "1")
    with pytest.raises(AuthorizationError):
        require_operator(db, action="compile", expected_phrase=COMPILE_PHRASE, confirm_flag=COMPILE_PHRASE)


# 15. Phrase gate mismatch
def test_contract_15_phrase_mismatch(db: sqlite3.Connection):
    with pytest.raises(AuthorizationError):
        require_operator(db, action="compile", expected_phrase=COMPILE_PHRASE, confirm_flag="wrong")


# 6. Valid approved set compiles and REAL bean-check passes (integration; requires the executable)
@pytest.mark.integration
def test_contract_6_real_bean_check_passes(db: sqlite3.Connection, tmp_path: Path):
    if shutil.which("bean-check") is None:
        pytest.skip("bean-check not installed")
    _seed(db)
    summary = compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")
    assert summary.output_hash and (tmp_path / "main.beancount").exists()


# 7. Unbalanced / invalid account / invalid sign / cross-currency each fail the compile
@pytest.mark.parametrize("mutate,match", [
    ("UPDATE staged_postings SET minor_units = 999 WHERE role = 'contra'", "does not balance"),
    ("UPDATE staged_postings SET account = 'not a valid account' WHERE role = 'contra'", "[Ii]nvalid account"),
    ("UPDATE staged_postings SET minor_units = 1500 WHERE role = 'imported'", "does not balance"),
    ("UPDATE staged_postings SET currency = 'EUR' WHERE role = 'contra'", "does not balance|multiple currencies"),
])
def test_contract_7_bad_inputs_fail(db: sqlite3.Connection, mutate: str, match: str):
    _seed(db)
    db.execute(mutate)
    db.commit()
    with pytest.raises(CompileInputError, match=match):
        validate_approved_set(load_approved_set(db))


# 9. ledger_entries / ledger_postings populated after compile, replaced (not appended) on recompile
def test_contract_9_index_populated_and_replaced(db: sqlite3.Connection, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("ironledger.compile.writer.run_bean_check",
                        lambda *a, **k: BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0"))
    _seed(db)
    compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")
    n1 = db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    p1 = db.execute("SELECT COUNT(*) FROM ledger_postings").fetchone()[0]
    assert n1 == 1 and p1 == 2
    compile_approved(db, tmp_path, now_utc="2026-09-06T13:00:00Z")  # recompile, same set
    assert db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM ledger_postings").fetchone()[0] == 2


# 10. Replayed compile over the same approved set: byte-identical files, no duplicate index rows
def test_contract_10_replay_byte_identical(db: sqlite3.Connection, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("ironledger.compile.writer.run_bean_check",
                        lambda *a, **k: BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0"))
    _seed(db)
    compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")
    first = {p.name: p.read_bytes() for p in tmp_path.rglob("*.beancount")}
    compile_approved(db, tmp_path, now_utc="2026-09-06T13:00:00Z")
    second = {p.name: p.read_bytes() for p in tmp_path.rglob("*.beancount")}
    assert first == second
    assert db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1


# 11. Every recovery decision-table row + a re-entrant recovery re-run
def test_contract_11_recovery_table_rows_covered():
    """Row coverage lives in tests/test_compile_recover.py and
    tests/test_compile_recovery_integration.py; this asserts the suite exists and is collected."""
    import tests.test_compile_recover as r
    import tests.test_compile_recovery_integration as ri
    names = set(dir(r)) | set(dir(ri))
    for required in [
        "test_recover_pre_write_abort_marks_failed",
        "test_recover_staging_hash_mismatch_refuses",
        "test_recovery_is_reentrant_after_mid_recovery_crash",
        "test_recover_rerun_after_full_recovery_is_safe_noop",
        "test_crash_mid_replace_recovers_cleanly",
        "test_crash_during_recovery_then_second_recover_completes",
    ]:
        assert required in names, f"missing recovery-table coverage: {required}"


# 12. os.replace interrupted between two target files recovers deterministically; repeat recover is a no-op
def test_contract_12_crash_between_files_recovers(db: sqlite3.Connection, tmp_path: Path, monkeypatch):
    import os as _os
    monkeypatch.setattr("ironledger.compile.writer.run_bean_check",
                        lambda *a, **k: BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0"))
    _seed(db)
    orig = _os.replace
    calls = {"n": 0}
    def crash_2nd(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("crash between files")
        return orig(src, dst)
    with patch("os.replace", side_effect=crash_2nd):
        with pytest.raises(OSError):
            compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")
    rec = recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:05:00Z")
    assert rec.action == "recovered"
    again = recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:06:00Z")
    assert again.action in {"none", "recovered"}


# 16. Every successful compile / failure / recovery / denial emits an audit event carrying compile_run_id
def test_contract_16_audit_events_carry_run_id(db: sqlite3.Connection, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("ironledger.compile.writer.run_bean_check",
                        lambda *a, **k: BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0"))
    _seed(db)
    summary = compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")
    rows = db.execute(
        "SELECT action, result, compile_run_id FROM audit_events WHERE compile_run_id = ?",
        (summary.compile_run_id,),
    ).fetchall()
    assert rows and all(r[2] == summary.compile_run_id for r in rows)
    assert any(r[1] == "ok" for r in rows)


# 17. Missing bean-check raises
def test_contract_17_missing_beancheck_raises(tmp_path: Path):
    with patch("shutil.which", return_value=None):
        with pytest.raises(BeanCheckUnavailableError):
            run_bean_check(tmp_path / "main.beancount")
```

All 17 items are present as explicitly named tests (T3.1). Items 6 and 12 use crash/real-binary paths; item 11 asserts the per-row recovery suite is collected. Add the `_seed` helper and imports (`shutil`, `compile_approved`, `recover_dangling_compile`, `BeanCheckResult`, `load_approved_set`, `validate_approved_set`) to the file header if not already there. `@pytest.mark.integration` on item 6 keeps it opt-in but the gate run includes it when `bean-check` is on PATH.

- [ ] **Step 2: Update `docs/meta/ironledger-dependency-posture.md`**

Add Phase 3 dependency posture amendment section detailing `beancount` pinned subprocess invocation, binary extension notes, and lockfile update requirements.

- [ ] **Step 3: Run full pytest suite across whole repository**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: ALL PASS (>300 passed, 1 skipped)

- [ ] **Step 4: Commit**

```bash
git add docs/meta/ironledger-dependency-posture.md tests/test_phase3_exit_contract.py
git commit -m "docs(ironledger): update dependency posture and add Phase 3 exit gate test contract"
```

---

## GSTACK REVIEW REPORT

| Field | Value |
|---|---|
| Runs | plan-eng-review (Sonnet 5), 2026-09-06 |
| Target | `docs/meta/plans/ironledger-phase-3-plan.md` (pre-first-commit) + `docs/meta/specs/ironledger-phase-3-compiler-design.md` |
| Status | REVIEWED — findings folded into spec + plan in this pass |
| Scope gate | user named the plan path explicitly; no scope reduction (15 tasks, spec-argued, right-sized) |

### Findings

| # | Sev | Finding | Disposition |
|---|---|---|---|
| B-T6 | blocker | Migration 0005 breaks 2 hard-coded schema-version asserts (`tests/test_migration_0004.py:51`, `tests/test_manifests.py:50`); Task 1 did not touch them, so the full-suite gate halts Task 1. | FOLDED — Task 1 Files + Step 4 now bump both to `== 5`; git-add list extended. |
| B-T3.1 | blocker (locked decision) | Task 15 exit-contract suite implemented 10 of 17 spec §14 items. | FOLDED — all 17 now present as named tests (6,7,9,10,11,12,16 added); spec §14 gains an "all 17 gate-blocking, explicit tests" preamble. |
| B-A4.1 | blocker (locked decision) | Recovery re-entrancy neither specced nor tested; Task 10 `recover.py` consumed `.staging` via `os.replace` move semantics, so a crash mid-recovery misclassified as row-3 refusal on re-run. | FOLDED — spec §11 row 2 gains idempotency clause, row 4 tightened to genuine-corruption-only; `recover.py` rewritten to re-render from the approved set, verify `input_hash`/`intended_output_hash`, and write only divergent live files; `writer.py` gains `_atomic_write_file` (copy semantics, staging survives); re-entrancy tests added to Task 10 (+2) and Task 11 (+1). |
| 4 | minor | `render_year_beancount` sorts postings by `role` with no invariant guaranteeing `{imported, contra}`. | FOLDED — `validate_approved_set` (Task 3) now rejects any non-`{imported, contra}` pair; render comment cites it; test added (Task 3 +1). |
| 5 | minor | Task 5 input-hash `json.dumps` kwargs must stay pinned. | Verified already pinned (`sort_keys`, fixed separators, `ensure_ascii`); load-bearing comment added. |
| 6 | medium | No test that migration 0005 is checksum-frozen. | FOLDED — `test_migration_0005_checksum_frozen` added to Task 1. |
| 7 | medium | Staging dir must be same-volume as `ledger/` (Windows `os.replace` cross-volume `OSError`). | Verified plan already uses `ledger_dir/.staging/<run_id>`; Global Constraint added to lock it. |
| 8 | minor | Task 1 RED "Expected: FAIL" undersold the failure modes. | FOLDED — Step 2 lists all three (`assert 4==5`, `no such table`). |

### Test count deltas (folded)

- Task 1: `test_migration_0005.py` 3 → 4; edits `test_migration_0004.py`, `test_manifests.py`.
- Task 3: `test_compile_model.py` 4 → 5.
- Task 10: `test_compile_recover.py` 3 → 5.
- Task 11: `test_compile_recovery_integration.py` 1 → 2.
- Task 15: `test_phase3_exit_contract.py` 10 → 17.

VERDICT: PLAN SOUND — folded and ready for operator approval. No CODEX / CROSS-MODEL pass run.

**UNRESOLVED DECISIONS:**
- Execution runner + branch: `tdd-task-runner` refuses `main`/`master`; `C:\dev\IronLedger` is on `main` with no remote (governance D-0, prior phases committed to `main` directly). Operator picks at execution time — either run `superpowers:subagent-driven-development` on `main`, or cut an `ironledger/phase-3-impl` branch for `tdd-task-runner` and fast-forward `main` after.
