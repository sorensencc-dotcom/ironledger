"""`ironledger` command tree (Phase 2a)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
    imp.add_argument("--confirm", default=None)
    imp.add_argument("--allow-partial", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "import":
        return _cmd_import(args)
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
                allow_partial=args.allow_partial,
            )
        except IngestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_INGEST

        print(render.render_import_result(result, mechanism))
        return _EXIT_OK
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
