"""`ironledger` command tree (Phase 2a)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ironledger.audit import append_audit_event
from ironledger.cli import auth, render
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.errors import AuthorizationError, IngestError
from ironledger.ingest.inbox import resolve_inbox_path
from ironledger.ingest.pipeline import run_import

_EXIT_OK = 0
_EXIT_AUTH = 3
_EXIT_INGEST = 4


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ironledger")
    parser.add_argument("--db", required=True, help="path to the SQLite ledger index")
    parser.add_argument("--config-dir", default="config", type=Path)
    parser.add_argument("--evidence-dir", default="evidence", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser(
        "import",
        help="acquire, parse, and stage one bank-export file",
        description=(
            "Authorized action. With a TTY, you are prompted for the phrase "
            "'import <resolved-path>'. Without a TTY, pass --confirm with that exact phrase."
        ),
    )
    imp.add_argument("path")
    imp.add_argument("--csv-profile", default=None)
    imp.add_argument("--importing-account", default=None)
    imp.add_argument("--confirm", default=None)
    imp.add_argument("--allow-partial", action="store_true")

    rev = sub.add_parser("review", help="inspect staged transactions (read-only in Phase 2a)")
    rev_sub = rev.add_subparsers(dest="review_command", required=True)
    rev_list = rev_sub.add_parser("list", help="list staged transactions")
    rev_list.add_argument("--status", default=None)
    rev_list.add_argument("--json", action="store_true")

    fit = sub.add_parser("fitid-trust", help="manage FITID trust records")
    fit_sub = fit.add_subparsers(dest="fitid_command", required=True)
    fit_add = fit_sub.add_parser(
        "add",
        help="trust FITID identity for one (institution, account)",
        description="Authorized action. Phrase: 'trust <institution>/<account>'.",
    )
    fit_add.add_argument("--institution", required=True)
    fit_add.add_argument("--account", required=True)
    fit_add.add_argument("--note", default="")
    fit_add.add_argument("--confirm", default=None)
    fit_list = fit_sub.add_parser("list", help="list FITID trust records")
    fit_list.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "import":
        return _cmd_import(args)
    if args.command == "review":
        return _cmd_review_list(args)
    if args.command == "fitid-trust":
        return _cmd_fitid_add(args) if args.fitid_command == "add" else _cmd_fitid_list(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


def _cmd_import(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            resolved = resolve_inbox_path(args.config_dir, args.path)
        except IngestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_INGEST

        try:
            mechanism = auth.require_operator(
                conn,
                action="import",
                subject=str(resolved),
                confirm=args.confirm,
                stdin_isatty=sys.stdin.isatty(),
                config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH

        try:
            result = run_import(
                conn,
                resolved,
                config_dir=args.config_dir,
                evidence_dir=args.evidence_dir,
                records_dir=args.evidence_dir / "source_records",
                csv_profile=args.csv_profile,
                importing_account=args.importing_account,
                allow_partial=args.allow_partial,
            )
        except IngestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_INGEST

        print(render.render_import_result(result, mechanism))
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_review_list(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        sql = (
            "SELECT staged_transaction_id, proposed_date, status, payee FROM staged_transactions"
        )
        params: tuple = ()
        if args.status:
            sql += " WHERE status = ?"
            params = (args.status,)
        sql += " ORDER BY proposed_date, staged_transaction_id"
        rows = []
        for stx_id, date, status, payee in conn.execute(sql, params):
            postings = conn.execute(
                "SELECT role, account, minor_units, currency FROM staged_postings "
                "WHERE staged_transaction_id = ? ORDER BY posting_index", (stx_id,)
            ).fetchall()
            summary = " | ".join(
                f"{role} {account or '<uncategorized>'} {mu} {cur}"
                for role, account, mu, cur in postings
            )
            rows.append({
                "staged_transaction_id": stx_id, "proposed_date": date,
                "status": status, "payee": payee, "posting_summary": summary,
            })
        print(render.render_staged_list(rows, as_json=args.json))
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_fitid_add(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        subject = f"{args.institution}/{args.account}"
        try:
            auth.require_operator(
                conn, action="fitid-trust-add", subject=subject, confirm=args.confirm,
                stdin_isatty=sys.stdin.isatty(), config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            conn.execute(
                "INSERT INTO fitid_trust_records (institution_id, account_id, added_at_utc, note) "
                "VALUES (?, ?, ?, ?)",
                (args.institution, args.account, now, args.note),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - surface any constraint issue as exit 4
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_INGEST
        append_audit_event(
            conn,
            actor="operator",
            action="fitid-trust add",
            target=subject,
            result="ok",
        )
        conn.commit()
        print(f"trusted {subject}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_fitid_list(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        rows = [
            {"institution_id": i, "account_id": a, "added_at_utc": t, "note": n}
            for i, a, t, n in conn.execute(
                "SELECT institution_id, account_id, added_at_utc, note FROM fitid_trust_records "
                "ORDER BY institution_id, account_id"
            )
        ]
        print(render.render_fitid_list(rows, as_json=args.json))
        return _EXIT_OK
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
