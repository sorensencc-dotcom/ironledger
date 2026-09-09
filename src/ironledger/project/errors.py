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
