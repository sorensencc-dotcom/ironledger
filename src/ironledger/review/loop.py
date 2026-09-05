"""Phase 2b guided review loop. Plain prompts over injected stdin/stdout; stdlib only."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ironledger.audit import append_audit_event
from ironledger.cli import auth
from ironledger.ingest.errors import AuthorizationError
from ironledger.ingest.identity import canonical_payee
from ironledger.review.approve_gate import ApproveGateError
from ironledger.review.rules import resolve_rule
from ironledger.review.state import approve, categorize, reject

__all__ = ["run_review_loop"]


def _now(now_utc: str | None) -> str:
    return now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT st.staged_transaction_id, st.status, st.payee, st.proposed_date, "
        "       imp.account, con.account "
        "FROM staged_transactions st "
        "JOIN staged_postings imp ON imp.staged_transaction_id = st.staged_transaction_id "
        "  AND imp.role = 'imported' "
        "JOIN staged_postings con ON con.staged_transaction_id = st.staged_transaction_id "
        "  AND con.role = 'contra' "
        "WHERE st.status IN ('pending', 'categorized') "
        "ORDER BY CASE st.status WHEN 'pending' THEN 0 ELSE 1 END, "
        "         st.created_at_utc ASC, st.staged_transaction_id ASC"
    ).fetchall()


def run_review_loop(
    conn: sqlite3.Connection,
    *,
    stdin,
    stdout,
    db_basename: str,
    confirm: str | None,
    stdin_isatty: bool,
    config_dir: str | Path,
    now_utc: str | None = None,
) -> dict[str, int]:
    counts = {"c": 0, "a": 0, "r": 0, "s": 0}
    append_audit_event(
        conn, actor="operator", action="review-session start", target=db_basename,
        result="ok", ts_utc=now_utc,
    )
    conn.commit()

    phrase_ok = False

    def _prompt(message: str) -> str:
        stdout.write(message)
        stdout.flush()
        return stdin.readline() or ""

    def ensure_phrase() -> None:
        nonlocal phrase_ok
        if phrase_ok:
            return
        try:
            auth.require_operator(
                conn, action="review-session", subject=db_basename, confirm=confirm,
                stdin_isatty=stdin_isatty, config_dir=config_dir, prompt=_prompt,
            )
        except AuthorizationError:
            _end(conn, db_basename, counts, now_utc)
            raise
        phrase_ok = True

    def read_line() -> str:
        line = stdin.readline()
        if line == "":
            return "q"
        return line.strip()

    for stx_id, status, payee, date, imp_acct, con_acct in _rows(conn):
        suggestion = (
            resolve_rule(conn, canonical_payee(payee), imp_acct, audit_skips=False, now_utc=now_utc)
            if con_acct is None else None
        )
        re_show = True
        while re_show:
            re_show = False
            stdout.write(
                f"\n{stx_id}  {date}  {status}  {payee}\n"
                f"  imported {imp_acct}   contra {con_acct or '<uncategorized>'}"
                + (f"   [rule suggests {suggestion}]" if suggestion else "")
                + "\n[c]ategorize  [a]pprove  [r]eject  [s]kip  [q]uit > "
            )
            stdout.flush()
            cmd = read_line()
            if cmd == "q":
                _end(conn, db_basename, counts, now_utc)
                return counts
            if cmd == "s":
                counts["s"] += 1
                continue
            if cmd == "c":
                stdout.write(f"account{f' [{suggestion}]' if suggestion else ''}: ")
                stdout.flush()
                entered = read_line()
                account = entered or (suggestion or "")
                if not account:
                    stdout.write("no account entered\n")
                    re_show = True
                    continue
                try:
                    categorize(conn, stx_id, account,
                               rule_id=None if entered else None, now_utc=now_utc)
                except ValueError as exc:
                    stdout.write(f"rejected: {exc}\n")
                    re_show = True
                    continue
                conn.commit()
                counts["c"] += 1
                status, con_acct, suggestion = "categorized", account, None
                re_show = True
                continue
            if cmd == "a":
                ensure_phrase()
                try:
                    approve(conn, stx_id, now_utc=now_utc)
                except ApproveGateError as exc:
                    stdout.write(f"cannot approve: {exc}\n")
                    re_show = True
                    continue
                conn.commit()
                counts["a"] += 1
                continue
            if cmd == "r":
                ensure_phrase()
                stdout.write("reason (optional): ")
                stdout.flush()
                reason = read_line() or None
                reject(conn, stx_id, reason=reason, now_utc=now_utc)
                conn.commit()
                counts["r"] += 1
                continue
            stdout.write(f"unknown command {cmd!r}\n")
            re_show = True

    _end(conn, db_basename, counts, now_utc)
    return counts


def _end(conn, db_basename, counts, now_utc) -> None:
    append_audit_event(
        conn, actor="operator",
        action=f"review-session end (c={counts['c']} a={counts['a']} r={counts['r']} s={counts['s']})",
        target=db_basename, result="ok", ts_utc=now_utc,
    )
    conn.commit()
