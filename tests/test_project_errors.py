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
