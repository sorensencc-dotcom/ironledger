# IronLedger Phase 4 analytics projection implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild a disposable SQLite projection from the compiled Beancount ledger, activate it atomically, and expose local `search` and `balances` CLI commands.

**Architecture:** A new `src/ironledger/project/` package (seven modules, locked) parses the Phase 3 Beancount dialect (`parse.py`), applies projection schema v1 (`schema.sql` + `migrate.py`), writes a staging SQLite with balances and FTS5 (`builder.py`), activates with compile-then-project locks and `os.replace` (`activate.py`), and queries the live file (`query.py`). CLI wiring lives in `cli/__main__.py`, phrases in `cli/auth.py`, human/JSON renderers in `cli/render.py`. The operational `--db` is not the analytical store. Search and balances never rebuild as a side effect.

**Tech Stack:** Python 3.12+ standard library (`sqlite3` including FTS5, `argparse`, `dataclasses`, `hashlib`, `os`, `pathlib`). No new runtime dependency. `beancount` stays on the `dev` extra and is never imported under `src/ironledger`. Tests use `pytest`.

**Repo:** `C:\dev\IronLedger` (local `main`, no remote, decision D-0). Run tests with `python -m pytest -q` from the repo root (`pyproject.toml` already sets `pythonpath = ["src"]`). Baseline before Task 1: **343 passed / 1 skipped** with `bean-check` on PATH; **342 / 2** without. Phase 4 tests only add.

**Spec:** `docs/meta/specs/ironledger-phase-4-projection-design.md` (DX + eng review folded in the working tree). The plan argues from that spec; executors read both.

**Author:** commits use `Iron-Hammer <iron-hammer@ironledger.local>`.

---

## Global Constraints

- Python `requires-python = ">=3.12"`. Standard library for runtime core. No new package. `ofxtools==1.1.1` remains the only runtime third-party import.
- `beancount` is never imported under `src/ironledger`. Phase 4 does not shell out to `bean-check`.
- Beancount files are the sole accounting authority. The projection is a disposable cache. Deleting `projection/` must not delete accounting truth.
- Monetary values are signed 64-bit integer minor units with explicit currency and scale from `src/ironledger/reference/iso4217.v2026-01.json`. No floating-point accounting arithmetic. Unlike currencies are never netted. Scale comes from the ISO-4217 table, not from counting decimal digits.
- Timestamps are UTC ISO-8601 `%Y-%m-%dT%H:%M:%SZ` (trailing `Z`). Functions accepting timestamps take `now_utc: str | None = None` and default to `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.
- Mutation-capable operations require `require_operator`, are blocked by safe mode, and emit an append-only audit event with `actor="operator"`.
- `ironledger project` is the only Phase 4 mutator. Phrase: `authorize project`. Safe mode denies. `search`, `balances`, and `project status` do not call `require_operator` and take no lock.
- Locks: acquire `ledger/.compile.lock` first, then `projection/.project.lock`, via shared `acquire_lock(directory, name=...)`. Release in reverse order. Keep `acquire_compile_lock` as a wrapper. Held → `CompileLockedError` or `ProjectLockedError`, exit 1, live projection untouched.
- Activation is `os.replace` of a checkpointed SQLite file then its manifest. Windows is a first-class host. No symlink flip. Staging lives at `projection/.staging/<build_id>/` on the same volume as the live files.
- `entry_id` **is** Beancount `staged-transaction-id`. `posting_id` is `"{staged-transaction-id}:{role}"` with `role` in `{imported, contra}`. Duplicate `staged-transaction-id` is a parse error.
- Year files: glob `txns/*.beancount` the same way `compile status` does, then require the `include "txns/YYYY.beancount"` set in `main.beancount` to equal that glob set.
- Search order: `ORDER BY entry_date ASC, posting_id ASC`. `--limit` default 50, hard max 500. `--offset` default 0. Empty or invalid FTS `MATCH` → exit 1, error formula, no traceback.
- Parent argparse: `--db` and `--ledger-dir` optional on the parent. `--db` required only on commands that open the operational DB. `search` / `balances` parse without `--db`. Invocation: `PYTHONPATH=src python -m ironledger.cli …`.
- Exit codes: `0` success, `1` parse/hash/lock/stale/missing projection (for search/balances) / input error, `3` authorization or safe-mode denial.
- All file writes use LF newlines and UTF-8.
- Seven-module layout is locked. Do not collapse it.
- D-0: no remote, do not push, do not invent an origin.
- Parked (do not implement in this plan): parser whitespace/comment/Unicode edge cases beyond UTF-8 + skip blank lines, `--projection-dir` path-safety beyond treating it as the projection root, leftover staging cleanup beyond removing the successful build_id dir, numbered performance gate.

---

## File structure

Created:

| Path | Responsibility |
|---|---|
| `src/ironledger/project/__init__.py` | Re-exports public types and `PROJECT_SCHEMA_VERSION` |
| `src/ironledger/project/errors.py` | Exception types + error-formula formatters |
| `src/ironledger/project/parse.py` | Closed dialect parser; round-trip dual of `compile/render.py` |
| `src/ironledger/project/schema.sql` | Projection schema v1 (STRICT + FTS5) |
| `src/ironledger/project/migrate.py` | Apply `schema.sql` to a new connection; `PROJECT_SCHEMA_VERSION = 1` |
| `src/ironledger/project/builder.py` | Staging write: accounts, entries, postings, balances, FTS, meta, checkpoint |
| `src/ironledger/project/activate.py` | Lock, hash check, parse, build, `os.replace`, audit |
| `src/ironledger/project/query.py` | Freshness check, `search`, `balances` on the live file |
| `README.md` | 10–20 line golden path |
| `tests/project_fixtures.py` | Shared sample `ApprovedSet`, write-ledger, seed-compile-run helpers |
| `tests/test_project_errors.py` | Error class hierarchy and formatter strings |
| `tests/test_project_parse.py` | Round-trip parse |
| `tests/test_project_parse_refusals.py` | Closed-dialect refusals, glob/include, duplicate stx-id |
| `tests/test_project_schema.py` | Schema apply, constraints, FTS5 present |
| `tests/test_project_lock.py` | Shared `acquire_lock`; compile wrapper unchanged |
| `tests/test_project_manifest.py` | `schema_version=` skip of operational migrator |
| `tests/test_project_builder.py` | Balances = SUM(postings); FTS fill; two-currency refusal |
| `tests/test_project_activate.py` | Rebuild, locks, hash mismatch, crash paths |
| `tests/test_project_query.py` | Search order, empty/invalid MATCH, freshness |
| `tests/test_cli_auth_phase4.py` | `authorize project` phrase and safe mode |
| `tests/test_cli_render_phase4.py` | Human/JSON search, balances, status, compile next-step |
| `tests/test_cli_project.py` | CLI wiring, optional `--db`, README argv smoke |
| `tests/test_phase4_exit_contract.py` | Gate items 1–21 |

Modified:

| Path | Why |
|---|---|
| `src/ironledger/compile/writer.py` | Generalize `acquire_lock`; keep `acquire_compile_lock` wrapper |
| `src/ironledger/manifests.py` | Optional `schema_version=` on generate **and** verify |
| `src/ironledger/cli/auth.py` | `PROJECT_PHRASE`, `_PREFIX["project"] = "authorize"` |
| `src/ironledger/cli/__main__.py` | Optional parent `--db`/`--ledger-dir`; `project`/`search`/`balances`; epilog |
| `src/ironledger/cli/render.py` | Project/search/balances/status renderers; compile next-step line |
| `src/ironledger/__init__.py` | Phase banner → 4 |
| `src/ironledger/cli/__init__.py` | Phase banner → 4 |
| `pyproject.toml` | `[tool.ironledger] phase = 4` |

Do not reuse `ironledger.db.migrations` against the projection file.

---

## Before Task 1

The spec at `docs/meta/specs/ironledger-phase-4-projection-design.md` has uncommitted DX+eng folds on top of `922290a`. Commit it first so implementation commits are code-only.

```bash
git add docs/meta/specs/ironledger-phase-4-projection-design.md
git commit -m "docs(ironledger): fold Phase 4 DX and eng review into spec"
```

Do not start Task 1 until that commit exists (or the working tree spec is already committed).

---

### Task 1: Projection error types and the error formula

**Files:**
- Create: `src/ironledger/project/__init__.py`
- Create: `src/ironledger/project/errors.py`
- Test: `tests/test_project_errors.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class ProjectError(Exception)`
  - `class ProjectParseError(ProjectError)` — attribute `path: str`, `line_no: int`, `snippet: str`
  - `class ProjectHashMismatchError(ProjectError)`
  - `class ProjectLockedError(ProjectError)`
  - `class ProjectStaleError(ProjectError)`
  - `class ProjectInputError(ProjectError)`
  - `format_parse_error(path, line_no, reason, snippet) -> str`
  - `format_hash_mismatch(*, on_disk: str, expected: str, ledger_dir: Path) -> str`
  - `format_stale(*, ledger_hash: str, projection_hash: str, ledger_dir: Path, db: str | None) -> str`
  - `format_locked(lock_file: Path, *, kind: str) -> str` with `kind` in `{"compile", "project"}`
  - `format_query_error(reason: str) -> str`

Every formatter returns **problem + cause + fix + values**. Parse errors include `path:line` and the offending snippet and state that the live projection is unchanged. Stale errors include short hashes (first 12 hex chars), `--ledger-dir`, and the copy-paste `python -m ironledger.cli project … --confirm "authorize project"` line. Hash-mismatch (rebuild vs compile run) hints `compile status` / `compile recover`. Lock errors name the lock path and the same remedy class as compile.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_errors.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.project.errors import (
    ProjectError,
    ProjectHashMismatchError,
    ProjectInputError,
    ProjectLockedError,
    ProjectParseError,
    ProjectStaleError,
    format_hash_mismatch,
    format_locked,
    format_parse_error,
    format_query_error,
    format_stale,
)


def test_hierarchy():
    assert issubclass(ProjectParseError, ProjectError)
    assert issubclass(ProjectHashMismatchError, ProjectError)
    assert issubclass(ProjectLockedError, ProjectError)
    assert issubclass(ProjectStaleError, ProjectError)
    assert issubclass(ProjectInputError, ProjectError)


def test_format_parse_error_has_path_line_snippet_and_unchanged():
    msg = format_parse_error(
        Path("ledger/txns/2026.beancount"),
        4,
        "unknown directive",
        "plugin \"beancount.plugins.auto_accounts\"",
    )
    assert "ledger/txns/2026.beancount:4:" in msg
    assert "unknown directive" in msg
    assert "plugin" in msg
    assert "unchanged" in msg.lower()


def test_format_stale_names_hashes_ledger_dir_and_copy_paste_project():
    msg = format_stale(
        ledger_hash="a" * 64,
        projection_hash="b" * 64,
        ledger_dir=Path("ledger"),
        db="ironledger.db",
    )
    assert "aaaaaaaaaaaa" in msg
    assert "bbbbbbbbbbbb" in msg
    assert "--ledger-dir" in msg
    assert "ledger" in msg
    assert "--confirm \"authorize project\"" in msg
    assert "python -m ironledger.cli project" in msg
    assert "--db ironledger.db" in msg


def test_format_stale_without_db_uses_placeholder():
    msg = format_stale(
        ledger_hash="c" * 64,
        projection_hash="d" * 64,
        ledger_dir=Path("ledger"),
        db=None,
    )
    assert "--db <db>" in msg
    assert "--confirm \"authorize project\"" in msg


def test_format_hash_mismatch_hints_compile_status_recover():
    msg = format_hash_mismatch(
        on_disk="e" * 64,
        expected="f" * 64,
        ledger_dir=Path("ledger"),
    )
    assert "eeeeeeeeeeee" in msg
    assert "ffffffffffff" in msg
    assert "compile status" in msg
    assert "compile recover" in msg


def test_format_locked_names_path():
    msg = format_locked(Path("projection/.project.lock"), kind="project")
    assert "projection/.project.lock" in msg.replace("\\", "/")
    assert "project" in msg.lower()


def test_format_query_error_no_traceback_shape():
    msg = format_query_error("empty search query")
    assert "empty search query" in msg.lower()
    assert "Traceback" not in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_project_errors.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.project'` (or `cannot import name`). No test-file syntax error.

- [ ] **Step 3: Write minimal implementation**

```python
# src/ironledger/project/__init__.py
from ironledger.project.errors import (
    ProjectError,
    ProjectHashMismatchError,
    ProjectInputError,
    ProjectLockedError,
    ProjectParseError,
    ProjectStaleError,
)

__all__ = [
    "ProjectError",
    "ProjectParseError",
    "ProjectHashMismatchError",
    "ProjectLockedError",
    "ProjectStaleError",
    "ProjectInputError",
]
```

```python
# src/ironledger/project/errors.py
from __future__ import annotations

from pathlib import Path


class ProjectError(Exception):
    """Base exception for projection rebuild and query failures."""


class ProjectParseError(ProjectError):
    def __init__(self, message: str, *, path: str = "", line_no: int = 0, snippet: str = "") -> None:
        super().__init__(message)
        self.path = path
        self.line_no = line_no
        self.snippet = snippet


class ProjectHashMismatchError(ProjectError):
    """Ledger bytes do not match the latest successful compile run."""


class ProjectLockedError(ProjectError):
    """Raised when the projection lock cannot be acquired."""


class ProjectStaleError(ProjectError):
    """Live projection is missing, hash-stale, schema-stale, or manifest-mismatched."""


class ProjectInputError(ProjectError):
    """Operator input or rebuild input that is well-formed but refused."""


def _short(hex_digest: str) -> str:
    return hex_digest[:12]


def format_parse_error(path: Path | str, line_no: int, reason: str, snippet: str) -> str:
    displayed = str(path).replace("\\", "/")
    return (
        f"{displayed}:{line_no}: {reason}\n"
        f"  {snippet.rstrip()}\n"
        "Live projection is unchanged. Fix the ledger (or recompile) and retry."
    )


def format_hash_mismatch(*, on_disk: str, expected: str, ledger_dir: Path) -> str:
    return (
        "Ledger hash does not match the latest successful compile.\n"
        f"  on disk:  {_short(on_disk)}…\n"
        f"  compile:  {_short(expected)}…\n"
        f"  --ledger-dir {ledger_dir}\n"
        "Cause: files on disk are not the last successful compile output.\n"
        f"Fix: python -m ironledger.cli compile status --ledger-dir {ledger_dir}\n"
        f"     python -m ironledger.cli compile recover --ledger-dir {ledger_dir}"
        ' --confirm "authorize compile recover"'
    )


def format_stale(
    *,
    ledger_hash: str,
    projection_hash: str,
    ledger_dir: Path,
    db: str | None,
) -> str:
    db_part = f" --db {db}" if db else " --db <db>"
    return (
        "Projection is stale relative to the ledger files.\n"
        f"  ledger:     {_short(ledger_hash)}…\n"
        f"  projection: {_short(projection_hash)}…\n"
        f"  --ledger-dir {ledger_dir}\n"
        "Cause: a compile succeeded (or files changed) and project has not been rebuilt.\n"
        f'Fix: python -m ironledger.cli project{db_part} --ledger-dir {ledger_dir}'
        ' --confirm "authorize project"'
    )


def format_locked(lock_file: Path, *, kind: str) -> str:
    process = "compile" if kind == "compile" else "project"
    label = "Compile" if kind == "compile" else "Projection"
    return (
        f"{label} lock is currently held at {lock_file}. "
        f"If no {process} is running, remove that file and retry."
    )


def format_query_error(reason: str) -> str:
    return (
        f"{reason}\n"
        "Cause: the search query is empty or is not valid FTS5 MATCH syntax.\n"
        "Fix: pass a non-empty FTS query (for example a payee or account token)."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_project_errors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/__init__.py src/ironledger/project/errors.py tests/test_project_errors.py
git commit -m "feat(project): add projection error types and formula"
```

---

### Task 2: Closed-dialect parser happy path (render round trip)

**Files:**
- Create: `src/ironledger/project/parse.py`
- Create: `tests/project_fixtures.py`
- Test: `tests/test_project_parse.py`

**Interfaces:**
- Consumes: `ironledger.compile.render.render_ledger`, `ironledger.compile.model.{ApprovedSet, ApprovedPosting, ApprovedTransaction}`, `ironledger.conventions.currency_scale`, `ProjectParseError`, `format_parse_error`
- Produces:
  - `@dataclass(frozen=True) class ParsedAccount: account: str; currency: str; open_date: str`
  - `@dataclass(frozen=True) class ParsedPosting: posting_id: str; entry_id: str; account: str; minor_units: int; currency: str; minor_unit_scale: int; source_document_id: str; source_record_id: str; identity_algo_version: int; identity_method: str; role: str`
  - `@dataclass(frozen=True) class ParsedEntry: entry_id: str; entry_date: str; payee: str; narration: str; staged_transaction_id: str; postings: tuple[ParsedPosting, ...]`
  - `@dataclass(frozen=True) class ParsedLedger: title: str; operating_currencies: tuple[str, ...]; accounts: tuple[ParsedAccount, ...]; entries: tuple[ParsedEntry, ...]; year_files: tuple[str, ...]`
  - `parse_amount(amount_str: str, scale: int) -> int` — exact inverse of `format_amount`; raises `ProjectParseError` if the fractional string is not exactly representable at `scale`
  - `unescape_beancount_string(val: str) -> str` — inverse of `escape_beancount_string`
  - `discover_year_files(ledger_dir: Path) -> list[str]` — `txns/*.beancount` as `txns/{name}`, same glob as compile status
  - `parse_ledger(ledger_dir: Path) -> ParsedLedger`

Parser rules (closed dialect, line-oriented, UTF-8 strict, skip blank lines only):

- `main.beancount`: `option "title" "…"`, one or more `option "operating_currency" "CUR"`, `include "accounts.beancount"`, then `include "txns/YYYY.beancount"` for each year file. Includes are relative to `ledger_dir`.
- After parsing main, `discover_year_files(ledger_dir)` must equal the include set of `txns/…` paths. Mismatch → `ProjectParseError` (tested in Task 3; happy path has a matching set).
- `accounts.beancount`: `YYYY-MM-DD open Account:Name CUR`. One account per line.
- Year files: flag `*`. Entry metadata required: `staged-transaction-id`. Posting order imported then contra. Posting metadata required exactly: `source-document-id`, `source-record-id`, `identity-algo-version`, `identity-method`. Amounts use ISO-4217 scale for that posting’s currency (`JPY 100` is scale 0; `USD 12.34` is scale 2).
- `entry_id = staged-transaction-id`. `posting_id = f"{staged-transaction-id}:{role}"` with `role` in `{imported, contra}` inferred from posting order (first posting imported, second contra). Duplicate `staged-transaction-id` → `ProjectParseError` (Task 3).
- Unknown directive, extra metadata key, missing required metadata, invalid account, unknown currency, or non-inverting amount → `ProjectParseError` with `path:line` + snippet (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/project_fixtures.py
from __future__ import annotations

from pathlib import Path

from ironledger.compile.hashing import compute_actual_output_hash
from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction
from ironledger.compile.render import render_ledger
from ironledger.db import migrations
from ironledger.db.connection import connect


def make_sample_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        staged_posting_id="sp-1", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="imported", posting_index=0, account="Assets:Checking",
        minor_units=-1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f" * 64,
    )
    p2 = ApprovedPosting(
        staged_posting_id="sp-2", staged_transaction_id="stx-1", source_record_id="rec-1",
        source_document_id="doc-1", role="contra", posting_index=1, account="Expenses:Food",
        minor_units=1234, currency="USD", minor_unit_scale=2, identity_algo_version=1,
        identity_method="fitid", identity_fingerprint="f" * 64,
    )
    t1 = ApprovedTransaction(
        staged_transaction_id="stx-1", source_record_id="rec-1", source_document_id="doc-1",
        proposed_date="2026-09-01", payee='Coffee "Shop"\\Cafe', narration="Latte",
        identity_algo_version=1, identity_method="fitid", identity_fingerprint="f" * 64,
        postings=(p1, p2),
    )
    return ApprovedSet(transactions=(t1,))


def make_jpy_set() -> ApprovedSet:
    p1 = ApprovedPosting(
        "sp-j1", "stx-jpy", "rec-1", "doc-1", "imported", 0, "Assets:Cash",
        -100, "JPY", 0, 1, "fitid", "e" * 64,
    )
    p2 = ApprovedPosting(
        "sp-j2", "stx-jpy", "rec-1", "doc-1", "contra", 1, "Expenses:Food",
        100, "JPY", 0, 1, "fitid", "e" * 64,
    )
    t1 = ApprovedTransaction(
        "stx-jpy", "rec-1", "doc-1", "2026-09-02", "Tokyo Cafe", "Yen",
        1, "fitid", "e" * 64, (p1, p2),
    )
    return ApprovedSet(transactions=(t1,))


def write_ledger(ledger_dir: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = ledger_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def write_rendered_ledger(ledger_dir: Path, approved_set: ApprovedSet | None = None) -> dict[str, bytes]:
    if approved_set is None:
        approved_set = make_sample_set()
    files = render_ledger(approved_set)
    write_ledger(ledger_dir, files)
    return files


def seed_successful_compile_run(db_path: Path, ledger_dir: Path, compile_run_id: str = "run-1") -> str:
    year_files = [f"txns/{p.name}" for p in sorted((ledger_dir / "txns").glob("*.beancount"))]
    actual = compute_actual_output_hash(ledger_dir, year_files)
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, actual_output_hash, status, started_at_utc, "
        " finished_at_utc, recovery_state) "
        "VALUES (?, '3.2.3', '0.1.0', ?, ?, ?, 'succeeded', "
        " '2026-09-08T12:00:00Z', '2026-09-08T12:00:01Z', 'none')",
        (compile_run_id, "a" * 64, actual, actual),
    )
    conn.commit()
    conn.close()
    return actual
```

```python
# tests/test_project_parse.py
from __future__ import annotations

from pathlib import Path

from ironledger.compile.render import format_amount
from ironledger.project.parse import parse_amount, parse_ledger, unescape_beancount_string
from tests.project_fixtures import make_jpy_set, make_sample_set, write_rendered_ledger


def test_parse_amount_inverts_format_amount():
    assert parse_amount(format_amount(-1234, 2), 2) == -1234
    assert parse_amount(format_amount(1234, 2), 2) == 1234
    assert parse_amount(format_amount(50, 2), 2) == 50
    assert parse_amount(format_amount(100, 0), 0) == 100
    assert parse_amount(format_amount(-5, 3), 3) == -5


def test_unescape_inverts_escape():
    assert unescape_beancount_string('Coffee \\"Shop\\"\\\\Cafe') == 'Coffee "Shop"\\Cafe'


def test_parse_ledger_round_trip_preserves_fields(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    parsed = parse_ledger(ledger_dir)

    assert parsed.operating_currencies == ("USD",)
    accounts = {a.account: a for a in parsed.accounts}
    assert accounts["Assets:Checking"].currency == "USD"
    assert accounts["Assets:Checking"].open_date == "2026-09-01"
    assert accounts["Expenses:Food"].currency == "USD"

    assert len(parsed.entries) == 1
    entry = parsed.entries[0]
    assert entry.entry_id == "stx-1"
    assert entry.staged_transaction_id == "stx-1"
    assert entry.entry_date == "2026-09-01"
    assert entry.payee == 'Coffee "Shop"\\Cafe'
    assert entry.narration == "Latte"
    assert len(entry.postings) == 2

    imported, contra = entry.postings
    assert imported.role == "imported"
    assert imported.posting_id == "stx-1:imported"
    assert imported.account == "Assets:Checking"
    assert imported.minor_units == -1234
    assert imported.currency == "USD"
    assert imported.minor_unit_scale == 2
    assert imported.source_document_id == "doc-1"
    assert imported.source_record_id == "rec-1"
    assert imported.identity_algo_version == 1
    assert imported.identity_method == "fitid"

    assert contra.role == "contra"
    assert contra.posting_id == "stx-1:contra"
    assert contra.account == "Expenses:Food"
    assert contra.minor_units == 1234


def test_parse_jpy_scale_zero_does_not_count_decimal_digits(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_jpy_set())
    parsed = parse_ledger(ledger_dir)
    imported = parsed.entries[0].postings[0]
    assert imported.currency == "JPY"
    assert imported.minor_unit_scale == 0
    assert imported.minor_units == -100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_project_parse.py -v`

Expected: FAIL with `ModuleNotFoundError` / `cannot import name 'parse_ledger'`. No syntax error in the test file.

- [ ] **Step 3: Write minimal implementation**

Implement `parse.py` as a line-oriented state machine that accepts exactly what `render_ledger` emits:

- Read files as UTF-8 (`newline=""` then split on `\n`, or `read_bytes().decode("utf-8")` and split on `\n`).
- Skip empty lines.
- `parse_amount`: optional leading `-`; if `scale == 0` the rest must be digits with no `.`; if `scale > 0` there must be exactly one `.` and exactly `scale` digits after it. Convert `sign + whole + frac` to int. Do **not** infer scale from digit count — caller passes ISO-4217 scale (`currency_scale(currency)`).
- Main file: regex/parse `option "title" "…"`, `option "operating_currency" "CUR"`, `include "accounts.beancount"`, `include "txns/{year}.beancount"`.
- Compare include set to `discover_year_files`.
- Accounts file: `^(\d{4}-\d{2}-\d{2}) open (\S+) ([A-Z]{3})$`. Validate account via `validate_account_name` and currency via `validate_currency`.
- Year file: header `^(\d{4}-\d{2}-\d{2}) \* "(.*)" "(.*)"$` with unescape on both strings; next line indent-2 `staged-transaction-id: "…"`; then two postings, each indent-2 `Account  amount CUR` followed by four indent-4 metadata keys in renderer order.
- Role: first posting `imported`, second `contra`. Raise if a third posting appears or if a required key is missing.
- `identity-algo-version` parses as `int`.

Keep the parser strict: any leftover non-blank line is an unknown directive.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_project_parse.py tests/test_project_errors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/parse.py tests/project_fixtures.py tests/test_project_parse.py
git commit -m "feat(project): parse Phase 3 Beancount dialect round-trip"
```

---

### Task 3: Parser refusals (closed dialect, glob/include, duplicate stx-id)

**Files:**
- Modify: `src/ironledger/project/parse.py` (refusals not already green from Task 2)
- Test: `tests/test_project_parse_refusals.py`

**Interfaces:**
- Consumes: `parse_ledger`, `ProjectParseError`
- Produces: every closed-dialect refusal raises `ProjectParseError` whose `str()` includes `path:line` (or equivalent) and a snippet of the bad line. Contract items 2, 16, 17.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_project_parse_refusals.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.project.errors import ProjectParseError
from ironledger.project.parse import parse_amount, parse_ledger
from tests.project_fixtures import make_sample_set, write_ledger, write_rendered_ledger


def _mutate_year(ledger_dir: Path, old: str, new: str) -> None:
    path = ledger_dir / "txns" / "2026.beancount"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def test_unknown_directive_raises_with_path_line_snippet(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    year = ledger_dir / "txns" / "2026.beancount"
    year.write_text(year.read_text(encoding="utf-8") + "plugin \"x\"\n", encoding="utf-8", newline="\n")
    with pytest.raises(ProjectParseError, match=r"txns/2026\.beancount:\d+:") as exc:
        parse_ledger(ledger_dir)
    assert "plugin" in str(exc.value)


def test_extra_metadata_key_raises(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    _mutate_year(ledger_dir, '    identity-method: "fitid"', '    identity-method: "fitid"\n    extra-key: "nope"')
    with pytest.raises(ProjectParseError, match="extra"):
        parse_ledger(ledger_dir)


def test_missing_required_metadata_raises(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    _mutate_year(ledger_dir, '  staged-transaction-id: "stx-1"\n', "")
    with pytest.raises(ProjectParseError, match="staged-transaction-id"):
        parse_ledger(ledger_dir)


def test_non_inverting_amount_raises():
    with pytest.raises(ProjectParseError):
        parse_amount("12.3", 2)
    with pytest.raises(ProjectParseError):
        parse_amount("12.345", 2)
    with pytest.raises(ProjectParseError):
        parse_amount("100.0", 0)


def test_include_set_disagrees_with_glob(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    extra = ledger_dir / "txns" / "2025.beancount"
    extra.write_text("", encoding="utf-8", newline="\n")
    with pytest.raises(ProjectParseError, match="include"):
        parse_ledger(ledger_dir)


def test_duplicate_staged_transaction_id(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    files = write_rendered_ledger(ledger_dir, make_sample_set())
    year = files["txns/2026.beancount"].decode("utf-8").rstrip() + "\n\n" + files["txns/2026.beancount"].decode("utf-8")
    write_ledger(ledger_dir, {**files, "txns/2026.beancount": year.encode("utf-8")})
    with pytest.raises(ProjectParseError, match="duplicate"):
        parse_ledger(ledger_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_project_parse_refusals.py -v`

Expected: FAIL on assertions / unraised `ProjectParseError` for the cases Task 2 did not yet refuse. Happy-path tests in `test_project_parse.py` stay green.

- [ ] **Step 3: Implement the refusals**

- Unknown non-blank line → `ProjectParseError(format_parse_error(...), path=..., line_no=..., snippet=...)`.
- Metadata keys must be exactly the required set in renderer order; any other key → extra; missing → missing.
- `parse_amount` refuses wrong decimal width.
- After reading main includes, `set(includes_txns) == set(discover_year_files(ledger_dir))` else parse error mentioning `include`.
- Track seen `staged-transaction-id`; second sighting → parse error mentioning `duplicate`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_project_parse.py tests/test_project_parse_refusals.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/parse.py tests/test_project_parse_refusals.py
git commit -m "feat(project): refuse closed-dialect parse violations"
```

---

### Task 4: Projection schema v1 and dedicated migrator

**Files:**
- Create: `src/ironledger/project/schema.sql`
- Create: `src/ironledger/project/migrate.py`
- Test: `tests/test_project_schema.py`

**Interfaces:**
- Consumes: `ironledger.db.connection.connect` (FK + WAL on file DBs). Do **not** call `ironledger.db.migrations.migrate` on this connection.
- Produces:
  - `PROJECT_SCHEMA_VERSION: int = 1` in `migrate.py`
  - `apply_schema(conn: sqlite3.Connection) -> None` — executes `schema.sql` (no `BEGIN`/`COMMIT` in the SQL file)
  - Tables: `projection_meta` (exactly one row via `singleton INTEGER PRIMARY KEY CHECK (singleton = 1)`), `proj_accounts`, `proj_entries`, `proj_postings`, `proj_balances`, `proj_fts` (FTS5, `tokenize='unicode61'`, `posting_id UNINDEXED`)

Schema (write **whole** in this task):

```sql
-- src/ironledger/project/schema.sql
-- IronLedger Phase 4: disposable analytics projection. Version 1.

CREATE TABLE projection_meta (
    singleton            INTEGER PRIMARY KEY CHECK (singleton = 1),
    compile_run_id       TEXT NOT NULL,
    ledger_input_hash    TEXT NOT NULL,
    ledger_output_hash   TEXT NOT NULL,
    schema_version       INTEGER NOT NULL CHECK (schema_version = 1),
    built_at_utc         TEXT NOT NULL CHECK (built_at_utc GLOB '????-??-??T??:??:??*Z'),
    beancount_version    TEXT NOT NULL,
    compiler_version     TEXT NOT NULL
) STRICT;

CREATE TABLE proj_accounts (
    account   TEXT PRIMARY KEY,
    currency  TEXT NOT NULL,
    open_date TEXT NOT NULL
) STRICT;

CREATE TABLE proj_entries (
    entry_id               TEXT PRIMARY KEY,
    entry_date             TEXT NOT NULL,
    payee                  TEXT NOT NULL,
    narration              TEXT NOT NULL,
    staged_transaction_id  TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE proj_postings (
    posting_id             TEXT PRIMARY KEY,
    entry_id               TEXT NOT NULL REFERENCES proj_entries (entry_id) ON DELETE CASCADE,
    account                TEXT NOT NULL,
    minor_units            INTEGER NOT NULL,
    currency               TEXT NOT NULL,
    minor_unit_scale       INTEGER NOT NULL,
    source_document_id     TEXT NOT NULL,
    source_record_id       TEXT NOT NULL,
    identity_algo_version  INTEGER NOT NULL,
    identity_method        TEXT NOT NULL
) STRICT;

CREATE TABLE proj_balances (
    account           TEXT NOT NULL,
    currency          TEXT NOT NULL,
    minor_units       INTEGER NOT NULL,
    minor_unit_scale  INTEGER NOT NULL,
    PRIMARY KEY (account, currency)
) STRICT;

CREATE VIRTUAL TABLE proj_fts USING fts5(
    payee,
    narration,
    account,
    posting_text,
    posting_id UNINDEXED,
    tokenize = 'unicode61'
);
```

```python
# src/ironledger/project/migrate.py
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def apply_schema(conn: sqlite3.Connection) -> None:
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
```

Re-export `PROJECT_SCHEMA_VERSION` from `project/__init__.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_schema.py
from __future__ import annotations

import sqlite3

import pytest

from ironledger.db.connection import connect
from ironledger.project.migrate import PROJECT_SCHEMA_VERSION, apply_schema


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "projection.sqlite")
    apply_schema(c)
    return c


def test_schema_version_constant():
    assert PROJECT_SCHEMA_VERSION == 1


def test_tables_exist(conn: sqlite3.Connection):
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert "projection_meta" in names
    assert "proj_accounts" in names
    assert "proj_entries" in names
    assert "proj_postings" in names
    assert "proj_balances" in names
    assert "proj_fts" in names


def test_projection_meta_accepts_exactly_one_row(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO projection_meta (singleton, compile_run_id, ledger_input_hash, "
        " ledger_output_hash, schema_version, built_at_utc, beancount_version, compiler_version) "
        "VALUES (1, 'run-1', ?, ?, 1, '2026-09-08T12:00:00Z', '3.2.3', '0.1.0')",
        ("a" * 64, "b" * 64),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projection_meta (singleton, compile_run_id, ledger_input_hash, "
            " ledger_output_hash, schema_version, built_at_utc, beancount_version, compiler_version) "
            "VALUES (1, 'run-2', ?, ?, 1, '2026-09-08T12:00:00Z', '3.2.3', '0.1.0')",
            ("c" * 64, "d" * 64),
        )


def test_posting_fk_and_entry_unique(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO proj_entries (entry_id, entry_date, payee, narration, staged_transaction_id) "
        "VALUES ('stx-1', '2026-09-01', 'Cafe', 'Latte', 'stx-1')"
    )
    conn.execute(
        "INSERT INTO proj_postings (posting_id, entry_id, account, minor_units, currency, "
        " minor_unit_scale, source_document_id, source_record_id, identity_algo_version, identity_method) "
        "VALUES ('stx-1:imported', 'stx-1', 'Assets:Checking', -1234, 'USD', 2, 'doc-1', 'rec-1', 1, 'fitid')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO proj_entries (entry_id, entry_date, payee, narration, staged_transaction_id) "
            "VALUES ('stx-2', '2026-09-01', 'X', 'Y', 'stx-1')"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_project_schema.py -v`

Expected: FAIL importing `apply_schema` / missing module.

- [ ] **Step 3: Write `schema.sql` and `migrate.py` as specified above. Re-export `PROJECT_SCHEMA_VERSION`.**

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_schema.py tests/test_project_parse.py tests/test_project_errors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/schema.sql src/ironledger/project/migrate.py src/ironledger/project/__init__.py tests/test_project_schema.py
git commit -m "feat(project): add projection schema v1 and migrator"
```

---

### Task 5: Shared lock helper

**Files:**
- Modify: `src/ironledger/compile/writer.py` (`acquire_compile_lock` becomes a wrapper around `acquire_lock`)
- Test: `tests/test_project_lock.py`
- Existing tests that must stay green: `tests/test_compile_writer_staging.py` (match `"Compile lock is currently held"`)

**Interfaces:**
- Consumes: existing `CompileLockedError`
- Produces:
  - `acquire_lock(directory: Path, name: str = ".compile.lock", *, error_cls: type[BaseException] | None = None) -> Generator[Path, None, None]`
  - `acquire_compile_lock(ledger_dir: Path)` remains and still raises `CompileLockedError` with the **same** message prefix `Compile lock is currently held at`
  - When `error_cls is ProjectLockedError` (or `name == ".project.lock"`), raise `ProjectLockedError` using `format_locked(..., kind="project")`
  - Same `O_CREAT|O_EXCL|O_WRONLY`, pid/since body, unlink-on-write-fail, unlink in `finally`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_lock.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.compile.errors import CompileLockedError
from ironledger.compile.writer import acquire_compile_lock, acquire_lock
from ironledger.project.errors import ProjectLockedError


def test_acquire_compile_lock_still_raises_compile_locked(tmp_path: Path):
    with acquire_compile_lock(tmp_path):
        with pytest.raises(CompileLockedError, match="Compile lock is currently held"):
            with acquire_compile_lock(tmp_path):
                pass


def test_acquire_lock_project_name_raises_project_locked(tmp_path: Path):
    with acquire_lock(tmp_path, name=".project.lock", error_cls=ProjectLockedError):
        with pytest.raises(ProjectLockedError, match="Projection lock is currently held"):
            with acquire_lock(tmp_path, name=".project.lock", error_cls=ProjectLockedError):
                pass


def test_compile_and_project_locks_are_independent(tmp_path: Path):
    with acquire_lock(tmp_path, name=".compile.lock"):
        with acquire_lock(tmp_path, name=".project.lock", error_cls=ProjectLockedError) as proj:
            assert proj.name == ".project.lock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_project_lock.py -v`

Expected: FAIL importing `acquire_lock`.

- [ ] **Step 3: Generalize in `writer.py`**

Replace `acquire_compile_lock` with:

```python
@contextmanager
def acquire_lock(
    directory: Path,
    name: str = ".compile.lock",
    *,
    error_cls: type[BaseException] | None = None,
) -> Generator[Path, None, None]:
    from ironledger.project.errors import ProjectLockedError, format_locked

    if error_cls is None:
        error_cls = CompileLockedError
    lock_file = directory / name
    directory.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if error_cls is CompileLockedError:
            raise CompileLockedError(
                f"Compile lock is currently held at {lock_file}. "
                f"If no compile is running, remove that file and retry."
            )
        raise error_cls(format_locked(lock_file, kind="project"))
    try:
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        os.write(fd, f"pid={os.getpid()}\nsince={since}\n".encode("utf-8"))
    except BaseException:
        os.close(fd)
        try:
            lock_file.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(fd)
    try:
        yield lock_file
    finally:
        if lock_file.exists():
            lock_file.unlink()


def acquire_compile_lock(ledger_dir: Path) -> Generator[Path, None, None]:
    with acquire_lock(ledger_dir, name=".compile.lock", error_cls=CompileLockedError) as lock_file:
        yield lock_file
```

Avoid an import cycle: `writer.py` must not import `project.activate`. Importing `project.errors` from `writer.py` is allowed (`errors.py` imports nothing from compile). If a cycle appears, move `acquire_lock` to a tiny `ironledger.compile.locks` module and re-export from `writer.py` — only do that if the cycle is real.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_lock.py tests/test_compile_writer_staging.py -v`

Expected: PASS (existing compile lock tests still match `Compile lock is currently held`).

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/compile/writer.py tests/test_project_lock.py
git commit -m "feat(compile): generalize acquire_lock for project"
```

---

### Task 6: Manifest `schema_version=` (skip operational migrator)

**Files:**
- Modify: `src/ironledger/manifests.py` (`generate_projection_manifest` and `verify_manifest`)
- Test: `tests/test_project_manifest.py`
- Existing tests that must stay green: `tests/test_manifests.py` (callers that omit `schema_version=` still use `migrations.current_version`)

**Interfaces:**
- Consumes: existing `generate_projection_manifest` / `verify_manifest`
- Produces: both functions take optional `schema_version: int | None = None`. When set, **do not** call `migrations.current_version(conn)`. Generate uses the passed int as `Manifest.schema_version`. Verify compares `parsed.schema_version` to that int (and still checks integrity + row counts + file entries). Phase 1 callers stay unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_manifest.py
from __future__ import annotations

from pathlib import Path

from ironledger.db.connection import connect
from ironledger.manifests import generate_projection_manifest, verify_manifest
from ironledger.project.migrate import PROJECT_SCHEMA_VERSION, apply_schema


def test_generate_with_schema_version_skips_operational_migrator(tmp_path: Path):
    db_path = tmp_path / "projection.sqlite"
    conn = connect(db_path)
    apply_schema(conn)
    conn.execute(
        "INSERT INTO projection_meta (singleton, compile_run_id, ledger_input_hash, "
        " ledger_output_hash, schema_version, built_at_utc, beancount_version, compiler_version) "
        "VALUES (1, 'run-1', ?, ?, 1, '2026-09-08T12:00:00Z', '3.2.3', '0.1.0')",
        ("a" * 64, "b" * 64),
    )
    conn.commit()
    manifest = generate_projection_manifest(
        conn,
        compile_run_id="run-1",
        ledger_input_hash="a" * 64,
        output_hash="b" * 64,
        db_path=db_path,
        created_ts_utc="2026-09-08T12:00:00Z",
        schema_version=PROJECT_SCHEMA_VERSION,
    )
    assert manifest.schema_version == PROJECT_SCHEMA_VERSION
    assert manifest.schema_version == 1
    assert "schema_migrations" not in (manifest.row_counts or {})
    assert (manifest.row_counts or {}).get("projection_meta") == 1
    result = verify_manifest(
        manifest, conn=conn, base_dir=tmp_path, schema_version=PROJECT_SCHEMA_VERSION
    )
    assert result.is_valid is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_project_manifest.py -v`

Expected: FAIL — `generate_projection_manifest` does not accept `schema_version=` and/or `migrations.current_version` errors on a projection connection (no `schema_migrations` table).

- [ ] **Step 3: Extend both helpers**

In `generate_projection_manifest`, after the integrity check:

```python
schema_ver = schema_version if schema_version is not None else migrations.current_version(conn)
```

Add `schema_version: int | None = None` to the signature.

In `verify_manifest`, when `conn is not None`:

```python
if schema_version is not None:
    current_ver = schema_version
else:
    current_ver = migrations.current_version(conn)
```

Do not change callers that omit the argument.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_manifest.py tests/test_manifests.py tests/test_manifests_injection.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/manifests.py tests/test_project_manifest.py
git commit -m "feat(manifests): allow explicit projection schema_version"
```

---

### Task 7: Builder — staging SQLite, balances, FTS, meta

**Files:**
- Create: `src/ironledger/project/builder.py`
- Test: `tests/test_project_builder.py`

**Interfaces:**
- Consumes: `ParsedLedger`, `apply_schema`, `PROJECT_SCHEMA_VERSION`, `generate_projection_manifest`, `render_manifest`, `connect`
- Produces:
  - `POSTING_TEXT` bag: `f"{account} {formatted_amount} {currency} {identity_method} {identity_algo_version}"` using `format_amount(minor_units, minor_unit_scale)`
  - `write_staging_projection(parsed: ParsedLedger, staging_dir: Path, *, compile_run_id: str, ledger_input_hash: str, ledger_output_hash: str, beancount_version: str, compiler_version: str, built_at_utc: str) -> Path` — returns path to `staging_dir / "projection.sqlite"`. Also writes `staging_dir / "projection.manifest.json"` via `generate_projection_manifest(..., schema_version=PROJECT_SCHEMA_VERSION, db_path=sqlite_path)` and `render_manifest`.
  - Inserts accounts, entries (`entry_id = staged_transaction_id`), postings (`posting_id` already on `ParsedPosting`), then `INSERT INTO proj_balances SELECT account, currency, SUM(minor_units), MIN(minor_unit_scale) FROM proj_postings GROUP BY account, currency`.
  - Fills `proj_fts` with explicit INSERTs (one row per posting). Triggers are not the correctness authority.
  - Writes `projection_meta` singleton row with `schema_version=1`.
  - Before return: `PRAGMA wal_checkpoint(TRUNCATE)` and close the connection so `-wal`/`-shm` are absent next to the staging sqlite.
  - If two currencies would land on one account (posting currency ≠ `proj_accounts.currency`, or two `ParsedAccount` rows for the same account with different currencies): raise `ProjectInputError` and do not leave a usable live file (this is staging; live is untouched by construction).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_builder.py
from __future__ import annotations

from pathlib import Path

from ironledger.db.connection import connect
from ironledger.project.builder import write_staging_projection
from ironledger.project.parse import parse_ledger
from tests.project_fixtures import make_sample_set, write_rendered_ledger


def test_builder_balances_equal_sum_of_postings(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    parsed = parse_ledger(ledger_dir)
    staging = tmp_path / "projection" / ".staging" / "build-1"
    sqlite_path = write_staging_projection(
        parsed,
        staging,
        compile_run_id="run-1",
        ledger_input_hash="a" * 64,
        ledger_output_hash="b" * 64,
        beancount_version="3.2.3",
        compiler_version="0.1.0",
        built_at_utc="2026-09-08T12:00:00Z",
    )
    assert sqlite_path.name == "projection.sqlite"
    assert not (staging / "projection.sqlite-wal").exists()
    assert (staging / "projection.manifest.json").is_file()

    conn = connect(sqlite_path)
    meta = conn.execute(
        "SELECT compile_run_id, schema_version FROM projection_meta WHERE singleton = 1"
    ).fetchone()
    assert meta == ("run-1", 1)
    rows = conn.execute(
        "SELECT b.account, b.currency, b.minor_units, "
        " (SELECT SUM(p.minor_units) FROM proj_postings p "
        "  WHERE p.account = b.account AND p.currency = b.currency) "
        "FROM proj_balances b"
    ).fetchall()
    assert rows
    for account, currency, bal, summed in rows:
        assert bal == summed, (account, currency, bal, summed)
    hits = conn.execute(
        "SELECT posting_id FROM proj_fts WHERE proj_fts MATCH 'Coffee' ORDER BY posting_id"
    ).fetchall()
    assert hits  # payee is indexed
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_project_builder.py -v`

Expected: FAIL importing `write_staging_projection`.

- [ ] **Step 3: Implement `builder.py`**

Open `staging_dir / "projection.sqlite"` via `connect`, `apply_schema`, insert rows, balances, FTS, meta, generate manifest with `schema_version=PROJECT_SCHEMA_VERSION`, write manifest JSON with LF, checkpoint, close. Create `staging_dir` with `mkdir(parents=True, exist_ok=True)`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_builder.py tests/test_project_schema.py tests/test_project_manifest.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/builder.py tests/test_project_builder.py
git commit -m "feat(project): write staging projection sqlite and FTS"
```

---

### Task 8: Two-currency-per-account rebuild refusal

**Files:**
- Modify: `src/ironledger/project/builder.py` and/or `parse.py` if two `open` lines are the injection
- Test: add to `tests/test_project_builder.py`

**Interfaces:**
- Consumes: Task 7 `write_staging_projection`
- Produces: a second currency on one account raises `ProjectInputError` (or `ProjectParseError`). `proj_balances` never stores two currencies that the CLI would add together; the CLI never prints a single number for two currencies (enforced here + Task 11 balances renderer).

- [ ] **Step 1: Write the failing test**

```python
def test_second_currency_on_one_account_refuses(tmp_path: Path):
    from ironledger.project.errors import ProjectInputError, ProjectParseError
    from ironledger.project.parse import parse_ledger
    from tests.project_fixtures import make_sample_set, write_rendered_ledger

    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    accounts = ledger_dir / "accounts.beancount"
    accounts.write_text(
        accounts.read_text(encoding="utf-8") + "2026-09-01 open Assets:Checking EUR\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises((ProjectInputError, ProjectParseError)):
        parsed = parse_ledger(ledger_dir)
        write_staging_projection(
            parsed,
            tmp_path / "staging",
            compile_run_id="run-1",
            ledger_input_hash="a" * 64,
            ledger_output_hash="b" * 64,
            beancount_version="3.2.3",
            compiler_version="0.1.0",
            built_at_utc="2026-09-08T12:00:00Z",
        )
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `python -m pytest tests/test_project_builder.py::test_second_currency_on_one_account_refuses -v`

Expected: FAIL (parse currently last-write-wins or accepts two opens).

- [ ] **Step 3: Refuse duplicate account opens with a different currency in `parse_ledger` (`ProjectParseError`) and, in the builder, refuse a posting whose currency ≠ `proj_accounts.currency` (`ProjectInputError`).**

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_builder.py tests/test_project_parse.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/parse.py src/ironledger/project/builder.py tests/test_project_builder.py
git commit -m "feat(project): refuse a second currency on one account"
```

---

### Task 9: Activate — locks, hash check, parse, replace

**Files:**
- Create: `src/ironledger/project/activate.py`
- Test: `tests/test_project_activate.py`

**Interfaces:**
- Consumes: `acquire_lock`, `acquire_compile_lock` wrapper, `get_latest_successful_run`, `compute_actual_output_hash`, `discover_year_files` / glob, `parse_ledger`, `write_staging_projection`, `append_audit_event`, error formatters
- Produces:
  - `@dataclass(frozen=True) class ProjectSummary: compile_run_id: str; schema_version: int; entry_count: int; posting_count: int; account_count: int; ledger_output_hash: str; projection_path: Path`
  - `default_projection_dir(ledger_dir: Path) -> Path` = `ledger_dir.parent / "projection"`
  - `rebuild_projection(conn: sqlite3.Connection, ledger_dir: Path, projection_dir: Path | None = None, *, now_utc: str | None = None) -> ProjectSummary`

Rebuild steps, in order:

1. `projection_dir = projection_dir or default_projection_dir(ledger_dir)`; `mkdir` projection dir.
2. `with acquire_lock(ledger_dir, name=".compile.lock"):` then nested `with acquire_lock(projection_dir, name=".project.lock", error_cls=ProjectLockedError):`
3. `run = get_latest_successful_run(conn)`; none → `ProjectInputError("no successful compile run")`.
4. Glob year files; `on_disk = compute_actual_output_hash(ledger_dir, year_files)`; must equal `run["actual_output_hash"]` else `ProjectHashMismatchError(format_hash_mismatch(...))`.
5. `parsed = parse_ledger(ledger_dir)` (include/glob mismatch is already a parse error).
6. `build_id = uuid.uuid4().hex`; staging = `projection_dir / ".staging" / build_id`.
7. `write_staging_projection(...)` using `run["input_hash"]` as `ledger_input_hash`, `on_disk` as `ledger_output_hash`, `run["beancount_version"]`, `run["compiler_version"]`.
8. `os.replace(staging / "projection.sqlite", projection_dir / "projection.sqlite")` then `os.replace(staging / "projection.manifest.json", projection_dir / "projection.manifest.json")`.
9. `shutil.rmtree(staging, ignore_errors=True)`.
10. `append_audit_event(conn, actor="operator", action="project", target=str(projection_dir), result="ok", compile_run_id=run["compile_run_id"])`; `conn.commit()`.
11. Return `ProjectSummary`.

On `ProjectError` / `CompileLockedError` after audit-capable failure: `append_audit_event(..., result="error")` when a connection is open and the failure is not auth (auth is CLI). Live projection must not be replaced.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_project_activate.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.compile.errors import CompileLockedError
from ironledger.compile.writer import acquire_compile_lock
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.project.errors import ProjectHashMismatchError, ProjectLockedError
from ironledger.project.parse import parse_ledger
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def world(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir, "run-1")
    conn = connect(str(db_path))
    migrations.migrate(conn)
    return conn, ledger_dir, tmp_path / "projection"


def test_rebuild_writes_live_sqlite_and_manifest(world):
    conn, ledger_dir, projection_dir = world
    summary = rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    assert summary.compile_run_id == "run-1"
    assert (projection_dir / "projection.sqlite").is_file()
    assert (projection_dir / "projection.manifest.json").is_file()
    parsed = parse_ledger(ledger_dir)
    live = connect(projection_dir / "projection.sqlite")
    n_entries = live.execute("SELECT count(*) FROM proj_entries").fetchone()[0]
    n_postings = live.execute("SELECT count(*) FROM proj_postings").fetchone()[0]
    assert n_entries == len(parsed.entries)
    assert n_postings == sum(len(e.postings) for e in parsed.entries)
    live.close()


def test_hash_mismatch_leaves_live_untouched(world):
    conn, ledger_dir, projection_dir = world
    (ledger_dir / "accounts.beancount").write_bytes(
        (ledger_dir / "accounts.beancount").read_bytes() + b"\n"
    )
    with pytest.raises(ProjectHashMismatchError):
        rebuild_projection(conn, ledger_dir, projection_dir)
    assert not (projection_dir / "projection.sqlite").exists()


def test_held_compile_lock_refuses(world):
    conn, ledger_dir, projection_dir = world
    with acquire_compile_lock(ledger_dir):
        with pytest.raises(CompileLockedError):
            rebuild_projection(conn, ledger_dir, projection_dir)
    assert not (projection_dir / "projection.sqlite").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_project_activate.py -v`

Expected: FAIL importing `rebuild_projection`.

- [ ] **Step 3: Implement `activate.py` as specified.**

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_activate.py tests/test_project_lock.py tests/test_project_builder.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/activate.py tests/test_project_activate.py
git commit -m "feat(project): rebuild projection under compile then project locks"
```

---

### Task 10: Activate crash paths (sqlite replace vs manifest replace)

**Files:**
- Modify: `src/ironledger/project/activate.py` only if the happy path already sequences the two `os.replace` calls (it must)
- Test: add to `tests/test_project_activate.py`

**Interfaces:**
- Consumes: `rebuild_projection`
- Produces: contract items 7 and 8. Crash before sqlite replace → previous live sqlite (or absent). Sqlite replace then crash before manifest replace → live sqlite is the new file, live manifest is the old file or absent; later `project status` / search / balances fail closed. This task asserts the on-disk files; status/search fail-closed is Task 12/14.

- [ ] **Step 1: Write the failing tests**

```python
def test_crash_before_sqlite_replace_keeps_previous(world, monkeypatch):
    conn, ledger_dir, projection_dir = world
    summary = rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    previous = (projection_dir / "projection.sqlite").read_bytes()
    import os
    real = os.replace

    def boom(src, dst):
        if Path(dst).name == "projection.sqlite":
            raise KeyboardInterrupt("simulated crash")
        return real(src, dst)

    monkeypatch.setattr("ironledger.project.activate.os.replace", boom)
    with pytest.raises(KeyboardInterrupt):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == previous


def test_crash_after_sqlite_before_manifest_leaves_mismatch(world, monkeypatch):
    conn, ledger_dir, projection_dir = world
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    old_manifest = (projection_dir / "projection.manifest.json").read_bytes()
    import os
    real = os.replace

    def boom(src, dst):
        if Path(dst).name == "projection.manifest.json":
            raise KeyboardInterrupt("simulated crash")
        return real(src, dst)

    monkeypatch.setattr("ironledger.project.activate.os.replace", boom)
    with pytest.raises(KeyboardInterrupt):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").is_file()
    assert (projection_dir / "projection.manifest.json").read_bytes() == old_manifest
```

Note: the second rebuild uses the same ledger bytes, so sqlite content may be identical except `built_at_utc`. That is still a valid crash-path: the **manifest** is the old file. If `os.replace` of sqlite is a no-op-looking write, still assert the manifest bytes did not change and sqlite exists.

- [ ] **Step 2: Run the new tests**

Run: `python -m pytest tests/test_project_activate.py::test_crash_before_sqlite_replace_keeps_previous tests/test_project_activate.py::test_crash_after_sqlite_before_manifest_leaves_mismatch -v`

Expected: FAIL if replace order is wrong or `os.replace` is not the module-level `os.replace`.

- [ ] **Step 3: Guarantee `activate.py` calls `os.replace` on sqlite then manifest, imported as module-global `os`.** Do not wrap both in one helper that cannot be interrupted between them.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_activate.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/activate.py tests/test_project_activate.py
git commit -m "test(project): crash before sqlite replace and between replaces"
```

---

### Task 11: Query — search, balances, order, empty/invalid MATCH

**Files:**
- Create: `src/ironledger/project/query.py`
- Test: `tests/test_project_query.py`

**Interfaces:**
- Consumes: live projection connection, `PROJECT_SCHEMA_VERSION`, `compute_actual_output_hash`, `discover_year_files` (or the same glob), `verify_manifest`, `parse_manifest`, error formatters
- Produces:
  - `@dataclass(frozen=True) class SearchHit: entry_date: str; payee: str; narration: str; account: str; minor_units: int; currency: str; staged_transaction_id: str; posting_id: str`
  - `@dataclass(frozen=True) class BalanceRow: account: str; minor_units: int; currency: str; minor_unit_scale: int`
  - `assert_fresh(ledger_dir: Path, projection_dir: Path, *, db: str | None = None) -> sqlite3.Connection` — opens live sqlite; raises `ProjectStaleError` if missing sqlite/manifest, `verify_manifest` fails, `projection_meta.schema_version != PROJECT_SCHEMA_VERSION`, or `projection_meta.ledger_output_hash != compute_actual_output_hash(...)`. Message uses `format_stale`. Returns an open connection on success.
  - `search(conn, query: str, *, limit: int = 50, offset: int = 0) -> list[SearchHit]`
    - empty/whitespace query → `ProjectInputError(format_query_error("empty search query"))`
    - `limit < 1` or `limit > 500` → `ProjectInputError`
    - `offset < 0` → `ProjectInputError`
    - SQL: FTS5 `MATCH` with a **bound** parameter, join `proj_postings` / `proj_entries`, `ORDER BY entry_date ASC, posting_id ASC LIMIT ? OFFSET ?`
    - `sqlite3.OperationalError` from MATCH → `ProjectInputError(format_query_error("invalid FTS query"))`
  - `balances(conn) -> list[BalanceRow]` — `SELECT … FROM proj_balances ORDER BY account ASC, currency ASC`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_project_query.py
from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.project.errors import ProjectInputError, ProjectStaleError
from ironledger.project.query import assert_fresh, balances, search
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def live(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir)
    conn = connect(str(db_path))
    migrations.migrate(conn)
    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    return ledger_dir, projection_dir


def test_search_hits_payee_and_is_stable(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    rows1 = search(conn, "Coffee")
    rows2 = search(conn, "Coffee")
    assert rows1 == rows2
    assert rows1[0].account in {"Assets:Checking", "Expenses:Food"}
    assert rows1[0].staged_transaction_id == "stx-1"
    posting_ids = [r.posting_id for r in rows1]
    assert posting_ids == sorted(posting_ids) or True  # order is date then posting_id
    ordered = search(conn, "Coffee")
    assert [h.posting_id for h in ordered] == sorted(
        (h.posting_id for h in ordered),
        key=lambda pid: (next(x.entry_date for x in ordered if x.posting_id == pid), pid),
    )
    conn.close()


def test_search_order_date_then_posting_id(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    hits = search(conn, "USD")
    pairs = [(h.entry_date, h.posting_id) for h in hits]
    assert pairs == sorted(pairs)
    conn.close()


def test_empty_and_invalid_match(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    with pytest.raises(ProjectInputError, match="empty"):
        search(conn, "  ")
    with pytest.raises(ProjectInputError, match="invalid"):
        search(conn, "AND")
    conn.close()


def test_balances_one_line_per_account_currency(live):
    ledger_dir, projection_dir = live
    conn = assert_fresh(ledger_dir, projection_dir)
    rows = balances(conn)
    assert [(r.account, r.currency) for r in rows] == sorted(
        (r.account, r.currency) for r in rows
    )
    checking = next(r for r in rows if r.account == "Assets:Checking")
    food = next(r for r in rows if r.account == "Expenses:Food")
    assert checking.minor_units == -1234
    assert food.minor_units == 1234
    conn.close()


def test_assert_fresh_missing_projection(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    with pytest.raises(ProjectStaleError):
        assert_fresh(ledger_dir, tmp_path / "projection")
```

Tighten `test_search_hits_payee_and_is_stable`: the important asserts are `rows1 == rows2` and that MATCH on payee returns the seeded posting. Drop the convoluted `or True` line — implementers must assert `rows1 == rows2` and `len(rows1) >= 1`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_project_query.py -v`

Expected: FAIL importing `search`.

- [ ] **Step 3: Implement `query.py`.** Use a bound parameter for MATCH. Catch `sqlite3.OperationalError`. Default FTS tokenizer is already `unicode61` from schema.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_query.py tests/test_project_activate.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/query.py tests/test_project_query.py
git commit -m "feat(project): search and balances against live projection"
```

---

### Task 12: Freshness after a new compile (stale search/balances)

**Files:**
- Modify: `src/ironledger/project/query.py` if `assert_fresh` does not yet compare file hash
- Test: add to `tests/test_project_query.py`

**Interfaces:**
- Consumes: `assert_fresh`
- Produces: after ledger bytes change (new `actual_output_hash`) without `project`, `assert_fresh` raises `ProjectStaleError` whose message includes both short hashes, `--ledger-dir`, and `--confirm "authorize project"`. Schema mismatch (`projection_meta.schema_version != 1`) uses the same stale formatter (copy-paste `project` line), not an in-place migration.

- [ ] **Step 1: Write the failing test**

```python
def test_stale_after_ledger_bytes_change(live):
    ledger_dir, projection_dir = live
    (ledger_dir / "accounts.beancount").write_bytes(
        (ledger_dir / "accounts.beancount").read_bytes() + b"; touched\n"
    )
    with pytest.raises(ProjectStaleError) as exc:
        assert_fresh(ledger_dir, projection_dir, db="ironledger.db")
    msg = str(exc.value)
    assert "--ledger-dir" in msg
    assert "--confirm \"authorize project\"" in msg
    assert "python -m ironledger.cli project" in msg
```

Also add `test_schema_mismatch_is_stale`: open live sqlite, `UPDATE projection_meta SET schema_version = 2` is blocked by CHECK — instead rebuild is not required; monkeypatch `PROJECT_SCHEMA_VERSION` comparison by passing a connection where meta.schema_version is read and compared to a fake current of 2 inside `assert_fresh` using the constant. Simpler approach: temporarily patch `ironledger.project.query.PROJECT_SCHEMA_VERSION` to `2` and expect `ProjectStaleError`.

```python
def test_schema_mismatch_is_stale(live, monkeypatch):
    ledger_dir, projection_dir = live
    monkeypatch.setattr("ironledger.project.query.PROJECT_SCHEMA_VERSION", 2)
    with pytest.raises(ProjectStaleError, match="authorize project"):
        assert_fresh(ledger_dir, projection_dir)
```

- [ ] **Step 2: Run the new tests**

Run: `python -m pytest tests/test_project_query.py::test_stale_after_ledger_bytes_change tests/test_project_query.py::test_schema_mismatch_is_stale -v`

Expected: FAIL if `assert_fresh` does not hash ledger files / does not treat schema mismatch as stale.

- [ ] **Step 3: Implement both checks in `assert_fresh`.** Never call `apply_schema` or migrate the live file in place.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_project_query.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/project/query.py tests/test_project_query.py
git commit -m "feat(project): fail closed when projection is stale"
```

---

### Task 13: Authorization phrase `authorize project`

**Files:**
- Modify: `src/ironledger/cli/auth.py`
- Test: `tests/test_cli_auth_phase4.py`

**Interfaces:**
- Consumes: `require_operator`
- Produces: `PROJECT_PHRASE = "authorize project"`; `_PREFIX["project"] = "authorize"`; `expected_phrase("project", "project") == "authorize project"`. Safe mode denies. Wrong phrase denies and writes `result="denied"`. Export `PROJECT_PHRASE` in `__all__`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_auth_phase4.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironledger.cli.auth import PROJECT_PHRASE, AuthorizationError, expected_phrase, require_operator
from ironledger.db import migrations
from ironledger.db.connection import connect


def _off(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    (d / "safe-mode.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    return d


def test_project_phrase_defined():
    assert PROJECT_PHRASE == "authorize project"
    assert expected_phrase("project", "project") == PROJECT_PHRASE


def test_project_authorized_with_confirm(tmp_path: Path):
    conn = connect(":memory:")
    migrations.migrate(conn)
    res = require_operator(
        conn,
        action="project",
        subject="project",
        confirm=PROJECT_PHRASE,
        stdin_isatty=False,
        config_dir=_off(tmp_path),
    )
    assert res == "confirm-flag"


def test_project_denied_wrong_phrase(tmp_path: Path):
    conn = connect(":memory:")
    migrations.migrate(conn)
    with pytest.raises(AuthorizationError):
        require_operator(
            conn,
            action="project",
            subject="project",
            confirm="wrong phrase",
            stdin_isatty=False,
            config_dir=_off(tmp_path),
        )
    row = conn.execute("SELECT result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert row[0] == "denied"


def test_project_denied_safe_mode(tmp_path: Path):
    conn = connect(":memory:")
    migrations.migrate(conn)
    d = tmp_path / "config-empty"
    d.mkdir()
    with pytest.raises(AuthorizationError, match="safe mode"):
        require_operator(
            conn,
            action="project",
            subject="project",
            confirm=PROJECT_PHRASE,
            stdin_isatty=False,
            config_dir=d,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_auth_phase4.py -v`

Expected: FAIL importing `PROJECT_PHRASE` / `expected_phrase("project", …)` KeyError.

- [ ] **Step 3: Add `PROJECT_PHRASE`, `_PREFIX["project"] = "authorize"`, and export.**

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_auth_phase4.py tests/test_cli_auth_phase3.py tests/test_cli_auth.py -v`

Expected: PASS (Phase 3 phrases unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/cli/auth.py tests/test_cli_auth_phase4.py
git commit -m "feat(cli): authorize project phrase and safe-mode gate"
```

---

### Task 14: CLI — optional parent `--db`/`--ledger-dir`, commands, renderers, compile next-step

**Files:**
- Modify: `src/ironledger/cli/__main__.py`
- Modify: `src/ironledger/cli/render.py`
- Test: `tests/test_cli_render_phase4.py`
- Test: `tests/test_cli_project.py`

**Interfaces:**
- Consumes: `rebuild_projection`, `assert_fresh`, `search`, `balances`, `get_latest_successful_run`, `PROJECT_PHRASE`, `AuthorizationError`, `ProjectError`, `CompileError`/`CompileLockedError`
- Produces:
  - Parent `--db` **not** required. Parent `--ledger-dir` optional (`dest="parent_ledger_dir"`). Subcommands that need a ledger dir also take `--ledger-dir` (`dest="ledger_dir"`). Resolver: `ledger_dir = args.ledger_dir or args.parent_ledger_dir`. Missing when required → stderr `error: the following arguments are required: --ledger-dir`, exit 2.
  - Commands that open operational DB (`compile`, `compile recover`, `import`, `review*`, `rule*`, `fitid-trust`, `project` rebuild): require `--db` at dispatch; missing → exit 2 with `required: --db`. `compile status` still requires `--db` (it reads `compile_runs`).
  - `project` rebuild: `require_operator(action="project", subject="project")`; catch `AuthorizationError` → print `denied: …`, exit 3; catch `ProjectError`/`CompileLockedError` → print `error: {exc}`, exit 1.
  - `project status`: no auth, no lock, no `migrations.migrate`. Missing projection → exit 0, human `nothing built yet` (JSON `{"status":"missing"}`). With `--db`, include latest successful compile comparison. Without `--db`, JSON **omits** the latest-compile object.
  - `search <query>` and `balances`: no `--db`, no auth, no lock. `--json`, `--limit` (default 50), `--offset` (default 0) on search. `--projection-dir` optional override on project/search/balances/status.
  - Human search line: `{date}  {payee}  {narration}  {account}  {minor_units}  {currency}  {staged_transaction_id}`
  - Human balances line: `{account}  {minor_units}  {currency}` sorted account then currency.
  - Parent `--help` epilog is the README golden path (two commands, `python -m ironledger.cli` form, `authorize project`).
  - `render_compile_summary` **gains** a trailing next-step when called with `db` and `ledger_dir`, **or** `_cmd_compile` prints a second block after the summary: `python -m ironledger.cli project --db {db} --ledger-dir {ledger_dir} --confirm "authorize project"`. Prefer printing from `_cmd_compile` so `render_compile_summary` signature stays compatible; add an optional `next_project_cmd: str | None = None` argument defaulting to `None` so existing tests that only check `succeeded` still pass, and a new test checks the substring.
  - Crash-between-replaces: `project status` reports mismatch (manifest verify fail or hash mismatch); `search`/`balances` exit 1.

Existing CLI tests pass `--db` before the subcommand and must stay green.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_render_phase4.py
from __future__ import annotations

import json

from ironledger.cli.render import (
    render_balances,
    render_project_status,
    render_search_hits,
)
from ironledger.project.query import BalanceRow, SearchHit


def test_render_search_human_and_json():
    hit = SearchHit(
        entry_date="2026-09-01",
        payee="Coffee Shop",
        narration="Latte",
        account="Expenses:Food",
        minor_units=1234,
        currency="USD",
        staged_transaction_id="stx-1",
        posting_id="stx-1:contra",
    )
    human = render_search_hits([hit], as_json=False)
    assert "2026-09-01" in human
    assert "Coffee Shop" in human
    assert "Latte" in human
    assert "Expenses:Food" in human
    assert "1234" in human
    assert "USD" in human
    assert "stx-1" in human
    payload = json.loads(render_search_hits([hit], as_json=True))
    assert payload[0]["staged_transaction_id"] == "stx-1"


def test_render_balances_never_nets_currencies():
    rows = [
        BalanceRow("Assets:Checking", -1234, "USD", 2),
        BalanceRow("Assets:Checking", -100, "EUR", 2),
    ]
    human = render_balances(rows, as_json=False)
    assert "USD" in human and "EUR" in human
    assert human.count("Assets:Checking") == 2


def test_render_project_status_omits_compile_when_absent():
    text = render_project_status(
        {"status": "ok", "ledger_output_hash": "a" * 64, "hash_matches_files": True},
        as_json=True,
    )
    payload = json.loads(text)
    assert "latest_run" not in payload
```

```python
# tests/test_cli_project.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ironledger.cli.__main__ import main
from ironledger.compile.beancheck import BeanCheckResult
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def env(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "safe-mode.json").write_text('{"enabled": false}', encoding="utf-8")
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    seed_successful_compile_run(db_path, ledger_dir)
    return db_path, config_dir, ledger_dir, tmp_path / "projection"


def test_help_lists_project_search_balances(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "project" in out
    assert "search" in out
    assert "balances" in out
    assert "python -m ironledger.cli" in out
    assert "authorize project" in out


def test_search_parses_without_db(env, capsys):
    db_path, config_dir, ledger_dir, projection_dir = env
    assert main([
        "--config-dir", str(config_dir),
        "--db", str(db_path),
        "project",
        "--ledger-dir", str(ledger_dir),
        "--projection-dir", str(projection_dir),
        "--confirm", "authorize project",
    ]) == 0
    rc = main([
        "--ledger-dir", str(ledger_dir),
        "search",
        "--projection-dir", str(projection_dir),
        "Coffee",
    ])
    assert rc == 0
    assert "Coffee" in capsys.readouterr().out


def test_project_wrong_phrase_exits_3(env):
    db_path, config_dir, ledger_dir, projection_dir = env
    rc = main([
        "--db", str(db_path),
        "--config-dir", str(config_dir),
        "project",
        "--ledger-dir", str(ledger_dir),
        "--projection-dir", str(projection_dir),
        "--confirm", "wrong phrase",
    ])
    assert rc == 3


def test_search_and_balances_do_not_require_operator(env, capsys):
    db_path, config_dir, ledger_dir, projection_dir = env
    main([
        "--config-dir", str(config_dir), "--db", str(db_path), "project",
        "--ledger-dir", str(ledger_dir), "--projection-dir", str(projection_dir),
        "--confirm", "authorize project",
    ])
    assert main(["--ledger-dir", str(ledger_dir), "balances", "--projection-dir", str(projection_dir)]) == 0
    out = capsys.readouterr().out
    assert "Assets:Checking" in out
    assert "-1234" in out


def test_compile_success_prints_next_project(tmp_path: Path, capsys):
    from ironledger.db import migrations
    from ironledger.db.connection import connect

    db_path = tmp_path / "ironledger.db"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "safe-mode.json").write_text('{"enabled": false}', encoding="utf-8")
    conn = connect(str(db_path))
    migrations.migrate(conn)
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
    ledger_dir = tmp_path / "ledger"
    success = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")
    with patch("ironledger.compile.writer.run_bean_check", return_value=success):
        rc = main([
            "--db", str(db_path), "--config-dir", str(config_dir),
            "compile", "--ledger-dir", str(ledger_dir), "--confirm", "authorize compile",
        ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "authorize project" in out
    assert "python -m ironledger.cli project" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli_render_phase4.py tests/test_cli_project.py -v`

Expected: FAIL — unknown command `project` / missing renderers / `--db` still required so `search` without `--db` errors.

- [ ] **Step 3: Implement argparse + dispatch + renderers**

Parent parser:

```python
parser = argparse.ArgumentParser(
    prog="ironledger",
    epilog=(
        "Golden path (from the repo root, after compile has succeeded):\n"
        "  python -m ironledger.cli project --db <db> --ledger-dir ledger "
        '--confirm "authorize project"\n'
        "  python -m ironledger.cli search --ledger-dir ledger coffee\n"
        "  python -m ironledger.cli balances --ledger-dir ledger"
    ),
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument("--db", required=False, default=None, help="path to the SQLite ledger index")
parser.add_argument("--ledger-dir", dest="parent_ledger_dir", default=None, type=Path)
```

Keep existing `--ledger-dir` on `compile` / `compile status` / `compile recover`. Add `project`, `project status`, `search`, `balances` subparsers. `search` takes positional `query`. Wire `_cmd_project`, `_cmd_project_status`, `_cmd_search`, `_cmd_balances`.

`_require_db(args)` / `_require_ledger_dir(args)` helpers print the argparse-style missing-arg line and return a sentinel or raise `SystemExit(2)` — prefer returning `None` and `return 2` so tests calling `main([...])` get `2` rather than `SystemExit` (except `--help`).

Catch `ProjectError` and `CompileLockedError` at the CLI boundary; print `error: {exc}` to stderr; exit 1. Do not print a traceback.

- [ ] **Step 4: Run tests including the existing compile CLI suite**

Run: `python -m pytest tests/test_cli_project.py tests/test_cli_render_phase4.py tests/test_cli_compile.py tests/test_cli_auth_phase3.py tests/test_cli_import.py -v`

Expected: PASS. Existing tests still pass `--db` as a parent option.

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/cli/__main__.py src/ironledger/cli/render.py tests/test_cli_project.py tests/test_cli_render_phase4.py
git commit -m "feat(cli): project, search, balances; optional parent --db"
```

---

### Task 15: README golden path, phase banners, argv smoke

**Files:**
- Create: `README.md` (repo root, 10–20 lines)
- Modify: `pyproject.toml` (`phase = 4`; comment no longer says projection out of scope)
- Modify: `src/ironledger/__init__.py`
- Modify: `src/ironledger/cli/__init__.py`
- Modify: `src/ironledger/cli/__main__.py` module docstring (no longer “Phase 2a”)
- Test: add smoke to `tests/test_cli_project.py` (contract items 14–15)

**Interfaces:**
- Consumes: Task 14 CLI
- Produces: README block exactly in the `python -m ironledger.cli` form; `--help` epilog matches that form; `[tool.ironledger] phase = 4`.

README content (keep ≤ 20 lines):

```markdown
# IronLedger

Local-first, single-operator financial OS. Beancount is the accounting
authority; SQLite is a disposable projection.

Requires Python 3.12+. From the repo root after a successful compile:

```text
$env:PYTHONPATH='src'

python -m ironledger.cli project --db <db> --ledger-dir ledger --confirm "authorize project"

python -m ironledger.cli search --ledger-dir ledger coffee

python -m ironledger.cli balances --ledger-dir ledger
```

`ironledger` on PATH is optional; tests and this README call `python -m ironledger.cli`.
```

`__init__.py` docstring:

```python
"""IronLedger: local-first, single-operator financial OS.

Beancount is the sole accounting authority; SQLite is a disposable,
rebuildable projection. Phase 4 ships `project`, `search`, and `balances`.
"""
```

- [ ] **Step 1: Write the failing smoke test** (add to `tests/test_cli_project.py`)

```python
def test_readme_argv_smoke(env, capsys):
    db_path, config_dir, ledger_dir, projection_dir = env
    assert main([
        "--db", str(db_path), "--config-dir", str(config_dir),
        "project", "--ledger-dir", str(ledger_dir),
        "--projection-dir", str(projection_dir),
        "--confirm", "authorize project",
    ]) == 0
    assert main(["--ledger-dir", str(ledger_dir), "search", "--projection-dir", str(projection_dir), "coffee"]) in {0, 1}
    # MATCH is case-insensitive under unicode61; either 0 with hits or 0 with empty is fine if query token matches payee
    rc_search = main(["--ledger-dir", str(ledger_dir), "search", "--projection-dir", str(projection_dir), "Coffee"])
    assert rc_search == 0
    rc_bal = main(["--ledger-dir", str(ledger_dir), "balances", "--projection-dir", str(projection_dir)])
    assert rc_bal == 0
```

Also assert README exists and contains `python -m ironledger.cli project` and `authorize project`.

```python
def test_readme_golden_path_text():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "python -m ironledger.cli project" in text
    assert "python -m ironledger.cli search" in text
    assert "python -m ironledger.cli balances" in text
    assert "authorize project" in text
```

```python
def test_phase_banner_is_four():
    import tomllib
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["ironledger"]["phase"] == 4
    from ironledger import __doc__ as pkg_doc
    assert "Phase 1 scope only" not in (pkg_doc or "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli_project.py::test_readme_golden_path_text tests/test_cli_project.py::test_phase_banner_is_four -v`

Expected: FAIL missing README / `phase == 3`.

- [ ] **Step 3: Write README and bump banners.**

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_project.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md pyproject.toml src/ironledger/__init__.py src/ironledger/cli/__init__.py src/ironledger/cli/__main__.py tests/test_cli_project.py
git commit -m "docs(ironledger): Phase 4 README golden path and banners"
```

---

### Task 16: Phase 4 exit contract (items 1–21) and full-suite gate

**Files:**
- Create: `tests/test_phase4_exit_contract.py`
- Modify: nothing in `src/` unless a contract item is red — then fix in the owning module, do not weaken the test

**Interfaces:**
- Consumes: every public function produced by Tasks 1–15
- Produces: one named test per contract item 1–21 in `docs/meta/specs/ironledger-phase-4-projection-design.md` §11. Full suite does not drop below the Phase 3 baseline; Phase 4 tests only add.

Map:

| Item | Test name | Already covered by | Exit-contract extra |
|---|---|---|---|
| 1 | `test_contract_1_render_parse_round_trip` | `test_project_parse.py` | Repeat here as the gate |
| 2 | `test_contract_2_parse_refusals_leave_live_untouched` | refusals | Rebuild a live projection first, then parse-fail a mutated copy of the **ledger** used by rebuild… actually parse does not touch projection. Item 2: unknown directive / extra metadata / missing metadata / non-inverting amount raise `ProjectParseError` **and** leave any pre-existing live projection byte-identical. Drive through `rebuild_projection` after mutating the ledger: hash mismatch or parse error, then compare live sqlite bytes. |
| 3 | `test_contract_3_balances_equal_sum` | builder | Gate copy |
| 4 | `test_contract_4_second_currency_refused` | Task 8 | Gate copy |
| 5 | `test_contract_5_delete_and_rebuild_identical_payload` | new | Delete live sqlite+manifest, rebuild, compare row counts + FTS posting_id set + payload digest excluding `built_at_utc` |
| 6 | `test_contract_6_fts_columns_and_rebuild_changes_hits` | builder/query | Change narration in Beancount, but then the compile hash will mismatch. For this item: write a new ledger + new compile run (update `actual_output_hash` in `--db`) then rebuild; FTS hit set must change. |
| 7 | `test_contract_7_crash_before_sqlite_replace` | Task 10 | Gate copy |
| 8 | `test_contract_8_crash_between_replaces_fail_closed` | Task 10 + CLI | After the mismatch, `main([..., "project", "status", ...])` is not exit-ok-as-fresh; `search` and `balances` return 1 |
| 9 | `test_contract_9_auth_surface` | Task 13/14 | Safe mode + wrong phrase exit 3 `denied`; search/balances/status do not call `require_operator` (spy or simply succeed without `--confirm`) |
| 10 | `test_contract_10_stale_after_new_compile` | Task 12 | New compile hash without project → search/balances exit 1 with hashes + copy-paste |
| 11 | `test_contract_11_no_import_beancount` | new | Walk `src/ironledger/**/*.py` and assert no `import beancount` / `from beancount` |
| 12 | (full suite, Step 4) | — | Not a unit test; the task’s full-suite command |
| 13 | `test_contract_13_search_balances_without_db` | Task 14 | Gate copy |
| 14 | `test_contract_14_help_and_epilog` | Task 14/15 | Gate copy |
| 15 | `test_contract_15_readme_argv_smoke` | Task 15 | Gate copy |
| 16 | `test_contract_16_include_glob_mismatch` | Task 3 | Through `rebuild_projection` so live stays unchanged |
| 17 | `test_contract_17_duplicate_stx_id` | Task 3 | Gate copy |
| 18 | `test_contract_18_held_compile_lock` | Task 9 | Gate copy |
| 19 | `test_contract_19_manifest_schema_version` | Task 6/7 | After rebuild, parse live manifest and assert `schema_version == projection_meta.schema_version == 1` |
| 20 | `test_contract_20_search_order_stable` | Task 11 | Two search runs identical |
| 21 | `test_contract_21_empty_and_invalid_fts` | Task 11 | Via `main([... "search", ...])` exit 1, stdout/stderr has no `Traceback` |

Item 2 sketch:

```python
def test_contract_2_parse_refusals_leave_live_untouched(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "db.sqlite"
    seed_successful_compile_run(db_path, ledger_dir)
    conn = connect(str(db_path)); migrations.migrate(conn)
    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    live = (projection_dir / "projection.sqlite").read_bytes()
    year = ledger_dir / "txns" / "2026.beancount"
    year.write_text(year.read_text(encoding="utf-8") + "plugin \"x\"\n", encoding="utf-8", newline="\n")
    # Hash will also mismatch; that still must leave live bytes identical.
    with pytest.raises((ProjectParseError, ProjectHashMismatchError)):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == live
```

If hash-mismatch fires first (it will — extra bytes), that still satisfies “leave live byte-identical”. Also run a **parse-only** refusal (call `parse_ledger` on a copy that still hashes if you restore bytes… simpler: call `parse_ledger` directly for unknown/extra/missing/non-inverting, **and** the rebuild-leaves-live assert above for the mutator path).

Item 5 payload digest: concatenate ordered `SELECT *` from `proj_accounts`, `proj_entries`, `proj_postings`, `proj_balances` and `SELECT posting_id FROM proj_fts ORDER BY posting_id`, hash sha256. Exclude `projection_meta.built_at_utc`.

Item 6: after first rebuild, record FTS posting_ids for `MATCH 'Latte'`. Rewrite ledger with narration `Mocha` via `ApprovedTransaction(..., narration="Mocha")`, recompute hash, `UPDATE compile_runs SET actual_output_hash=?, input_hash=?` (or insert a new succeeded run), rebuild, assert `'Latte'` hit set is empty and `'Mocha'` is non-empty.

- [ ] **Step 1: Write `tests/test_phase4_exit_contract.py` with all 20 unit tests (item 12 is the suite command).** Each test function name must start with `test_contract_{n}_`.

- [ ] **Step 2: Run the contract file**

Run: `python -m pytest tests/test_phase4_exit_contract.py -v`

Expected: FAIL only if a named item is actually uncovered. If everything is already green, this step is still required — the file is the gate artifact.

- [ ] **Step 3: Fix any red item in the owning module.** Do not skip or xfail.

- [ ] **Step 4: Full suite**

Run: `python -m pytest -q`

Expected: **≥ 343 passed / 1 skipped** with `bean-check` on PATH (Phase 3 baseline plus Phase 4). If `bean-check` is missing, **≥ 342 passed / 2 skipped**. No new skips. No pre-existing test red.

Also grep: no `import beancount` under `src/ironledger` (item 11).

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase4_exit_contract.py
git commit -m "test(project): Phase 4 exit contract items 1-21"
```

---

## Execution notes

- Stay on `main` (D-0, no remote). `tdd-task-runner` refuses `main`; this repo’s prior phases committed to `main` directly. Operator picks at execution time: run subagent-driven-development on `main`, or cut `ironledger/phase-4-impl` and fast-forward after.
- Do not push. Do not add an `origin`.
- Do not import `beancount` under `src/`.
- Do not collapse the seven-module layout.
- Do not start implementation until the operator approves this plan in the transcript and picks Subagent-Driven vs Inline.
- After ship: `/devex-review` (Pass 8 boomerang). Not part of this plan’s tasks.
)
