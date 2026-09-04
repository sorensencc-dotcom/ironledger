"""Categorization rule model, resolution, and CRUD (Phase 2b)."""

from __future__ import annotations

import re
import sqlite3

from ironledger.audit import append_audit_event

__all__ = ["RuleError", "resolve_rule"]


class RuleError(ValueError):
    """A rule definition is malformed (bad match_type or uncompilable regex)."""


def resolve_rule(
    conn: sqlite3.Connection,
    canonical_payee_value: str,
    importing_account: str,
    *,
    audit_skips: bool = True,
    now_utc: str | None = None,
) -> str | None:
    """Return the winning active rule's target_account for this payee and account, or None.

    `canonical_payee_value` must already be canonicalized by the caller
    (`ironledger.ingest.identity.canonical_payee`). A stored regex rule that
    fails to compile is skipped; it never aborts resolution. When `audit_skips`
    is True (import staging, auto-match) the skip is recorded as one audit
    event. When False (`review show`, the loop suggestion) nothing is written —
    those are read paths.
    """
    rows = conn.execute(
        "SELECT rule_id, match_type, pattern, target_account FROM categorization_rules "
        "WHERE active = 1 AND (importing_account IS NULL OR importing_account = ?) "
        "ORDER BY priority ASC, created_at_utc ASC",
        (importing_account,),
    ).fetchall()

    for rule_id, match_type, pattern, target_account in rows:
        if match_type == "exact":
            if canonical_payee_value == pattern:
                return target_account
        elif match_type == "prefix":
            if canonical_payee_value.startswith(pattern):
                return target_account
        elif match_type == "regex":
            try:
                compiled = re.compile(pattern)
            except re.error:
                if audit_skips:
                    append_audit_event(
                        conn,
                        actor="operator",
                        action="rule resolve (skipped uncompilable regex)",
                        target=rule_id,
                        result="error",
                        ts_utc=now_utc,
                    )
                continue
            if compiled.search(canonical_payee_value) is not None:
                return target_account
    return None
