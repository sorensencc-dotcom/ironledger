"""Categorization rule model, resolution, and CRUD (Phase 2b)."""

from __future__ import annotations

import re
import sqlite3
import uuid

from ironledger.audit import append_audit_event
from ironledger.conventions import ConventionError, validate_account_name

__all__ = ["RuleError", "resolve_rule", "resolve_rule_row", "RuleExistsError", "add_rule", "disable_rule", "list_rules", "persist_exact_rule"]


class RuleError(ValueError):
    """A rule definition is malformed (bad match_type or uncompilable regex)."""


class RuleExistsError(RuleError):
    """A rule with the same (match_type, pattern, importing_account) already exists."""

    def __init__(self, existing_rule_id: str) -> None:
        super().__init__(
            f"a rule for this pattern and scope already exists: {existing_rule_id}. "
            f"Run 'ironledger rule disable {existing_rule_id}' first."
        )
        self.existing_rule_id = existing_rule_id


_MATCH_TYPES = ("exact", "prefix", "regex")


def _new_rule_id() -> str:
    return f"rule:{uuid.uuid4().hex}"


def _validate_definition(match_type: str, pattern: str, target_account: str,
                         importing_account: str | None) -> None:
    if match_type not in _MATCH_TYPES:
        raise RuleError(f"match_type {match_type!r} is not one of {_MATCH_TYPES}")
    if not pattern:
        raise RuleError("pattern must be a non-empty string")
    if match_type == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            raise RuleError(f"regex pattern does not compile: {exc}") from exc
    try:
        validate_account_name(target_account)
        if importing_account is not None:
            validate_account_name(importing_account)
    except ConventionError as exc:
        raise RuleError(str(exc)) from exc


def _insert(conn, *, rule_id, match_type, pattern, importing_account, target_account,
            priority, now_utc):
    ts = now_utc or _now()
    try:
        conn.execute(
            "INSERT INTO categorization_rules (rule_id, match_type, pattern, importing_account, "
            " target_account, priority, active, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (rule_id, match_type, pattern, importing_account, target_account, priority, ts),
        )
    except sqlite3.IntegrityError as exc:
        existing = conn.execute(
            "SELECT rule_id FROM categorization_rules "
            "WHERE match_type = ? AND pattern = ? AND importing_account IS ?",
            (match_type, pattern, importing_account),
        ).fetchone()
        if existing is not None:
            raise RuleExistsError(existing[0]) from exc
        raise RuleError(f"rule insert violated a constraint: {exc}") from exc


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_rule(conn, *, match_type, pattern, target_account, importing_account=None,
             priority=100, now_utc=None) -> str:
    _validate_definition(match_type, pattern, target_account, importing_account)
    rule_id = _new_rule_id()
    _insert(conn, rule_id=rule_id, match_type=match_type, pattern=pattern,
            importing_account=importing_account, target_account=target_account,
            priority=priority, now_utc=now_utc)
    append_audit_event(
        conn, actor="operator",
        action=f"rule add ({match_type} {pattern} -> {target_account})",
        target=rule_id, result="ok", ts_utc=now_utc,
    )
    return rule_id


def persist_exact_rule(conn, *, canonical_payee_value, importing_account, target_account,
                       now_utc=None) -> str:
    _validate_definition("exact", canonical_payee_value, target_account, importing_account)
    rule_id = _new_rule_id()
    _insert(conn, rule_id=rule_id, match_type="exact", pattern=canonical_payee_value,
            importing_account=importing_account, target_account=target_account,
            priority=50, now_utc=now_utc)
    append_audit_event(
        conn, actor="operator",
        action=f"rule add (exact {canonical_payee_value} -> {target_account})",
        target=rule_id, result="ok", ts_utc=now_utc,
    )
    return rule_id


def disable_rule(conn, rule_id: str, *, now_utc=None) -> None:
    ts = now_utc or _now()
    updated = conn.execute(
        "UPDATE categorization_rules SET active = 0, disabled_at_utc = ? "
        "WHERE rule_id = ? AND active = 1",
        (ts, rule_id),
    ).rowcount
    if updated == 0:
        raise RuleError(f"rule {rule_id!r} is unknown or already disabled")
    append_audit_event(
        conn, actor="operator", action="rule disable", target=rule_id, result="ok", ts_utc=now_utc,
    )


def list_rules(conn) -> list[dict]:
    cols = ["rule_id", "match_type", "pattern", "importing_account", "target_account",
            "priority", "active", "created_at_utc", "disabled_at_utc"]
    return [
        dict(zip(cols, row))
        for row in conn.execute(
            f"SELECT {', '.join(cols)} FROM categorization_rules "
            "ORDER BY priority ASC, created_at_utc ASC"
        )
    ]


def resolve_rule_row(
    conn: sqlite3.Connection,
    canonical_payee_value: str,
    importing_account: str,
    *,
    audit_skips: bool = True,
    now_utc: str | None = None,
) -> tuple[str, str] | None:
    """Like resolve_rule but returns (rule_id, target_account) or None.

    `audit_skips` has the same meaning as in `resolve_rule`: True records an
    uncompilable-regex skip as one audit event; False writes nothing.
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
                return rule_id, target_account
        elif match_type == "prefix":
            if canonical_payee_value.startswith(pattern):
                return rule_id, target_account
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
                return rule_id, target_account
    return None


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
    hit = resolve_rule_row(
        conn, canonical_payee_value, importing_account, audit_skips=audit_skips, now_utc=now_utc
    )
    return None if hit is None else hit[1]
