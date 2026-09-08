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
from ironledger.ingest.identity import canonical_payee
from ironledger.ingest.inbox import resolve_inbox_path
from ironledger.ingest.pipeline import run_import
from ironledger.review import rules as rules_mod
from ironledger.review import state
from ironledger.review.approve_gate import ApproveGateError
from ironledger.review.loop import run_review_loop
from ironledger.review.rules import RuleError, RuleExistsError, resolve_rule
from ironledger.review.state import ReviewStateError

from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.errors import BeanCheckFailedError, BeanCheckUnavailableError, CompileError, CompileInputError
from ironledger.compile import hashing, journal, recover, writer

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_AUTH = 3
_EXIT_INGEST = 4
_EXIT_STATE = 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ironledger")
    parser.add_argument("--db", required=True, help="path to the SQLite ledger index")
    parser.add_argument("--config-dir", default="config", type=Path)
    parser.add_argument("--evidence-dir", default="evidence", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    # compile command tree
    comp = sub.add_parser("compile", help="compile approved staged transactions into Beancount ledger")
    comp.add_argument("--ledger-dir", default=None, type=Path, help="path to the output ledger directory")
    comp.add_argument("--confirm", default=None, help="confirmation phrase for operator authorization")
    comp_sub = comp.add_subparsers(dest="compile_command", required=False)

    comp_status = comp_sub.add_parser("status", help="show status of ledger compilation and crash recovery")
    comp_status.add_argument("--ledger-dir", required=True, type=Path, help="path to the output ledger directory")
    comp_status.add_argument("--json", action="store_true", help="render status as JSON")

    comp_recover = comp_sub.add_parser("recover", help="recover an interrupted compile run")
    comp_recover.add_argument("--ledger-dir", required=True, type=Path, help="path to the output ledger directory")
    comp_recover.add_argument("--confirm", default=None, help="confirmation phrase for operator authorization")

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

    rev = sub.add_parser("review", help="inspect and progress staged transactions")
    rev_sub = rev.add_subparsers(dest="review_command", required=False)
    rev.add_argument("--confirm", default=None)
    rev_list = rev_sub.add_parser("list", help="list staged transactions")
    rev_list.add_argument("--status", default=None)
    rev_list.add_argument("--json", action="store_true")

    rev_show = rev_sub.add_parser("show", help="show one staged transaction")
    rev_show.add_argument("staged_transaction_id")
    rev_show.add_argument("--json", action="store_true")

    rev_cat = rev_sub.add_parser(
        "categorize", help="set the contra account",
        description="Safe-mode gated; no phrase. Advances a pending row to categorized.",
    )
    rev_cat.add_argument("staged_transaction_id")
    rev_cat.add_argument("target_account")
    rev_cat.add_argument("--persist-rule", action="store_true")
    rev_cat.add_argument("--confirm", default=None)  # accepted, unused; keeps a uniform surface

    rev_am = rev_sub.add_parser(
        "auto-match", help="apply rules to pending NULL-contra rows",
        description="Authorized action. Phrase: 'auto-match <importing-account|all>'.",
    )
    rev_am.add_argument("--importing-account", default=None)
    rev_am.add_argument("--confirm", default=None)

    rev_ap = rev_sub.add_parser("approve", help="approve a staged transaction",
                                description="Authorized action. Phrase: 'approve <id>'.")
    rev_ap.add_argument("staged_transaction_id")
    rev_ap.add_argument("--confirm", default=None)

    rev_rj = rev_sub.add_parser("reject", help="reject a staged transaction",
                                description="Authorized action. Phrase: 'reject <id>'.")
    rev_rj.add_argument("staged_transaction_id")
    rev_rj.add_argument("--reason", default=None)
    rev_rj.add_argument("--confirm", default=None)

    rev_ro = rev_sub.add_parser("reopen", help="return a categorized or rejected row to pending",
                                description="Authorized action. Phrase: 'reopen <id>'.")
    rev_ro.add_argument("staged_transaction_id")
    rev_ro.add_argument("--confirm", default=None)

    rule = sub.add_parser("rule", help="manage categorization rules")
    rule_sub = rule.add_subparsers(dest="rule_command", required=True)
    rule_add = rule_sub.add_parser("add", help="add a categorization rule",
                                   description="Authorized action. Phrase: 'rule <target-account>'.")
    rule_add.add_argument("--match-type", required=True, choices=["exact", "prefix", "regex"])
    rule_add.add_argument("--pattern", required=True)
    rule_add.add_argument("--account", required=True)
    rule_add.add_argument("--importing-account", default=None)
    rule_add.add_argument("--priority", type=int, default=100)
    rule_add.add_argument("--confirm", default=None)
    rule_list = rule_sub.add_parser("list", help="list categorization rules")
    rule_list.add_argument("--json", action="store_true")
    rule_dis = rule_sub.add_parser("disable", help="disable a rule",
                                   description="Authorized action. Phrase: 'rule-disable <rule_id>'.")
    rule_dis.add_argument("rule_id")
    rule_dis.add_argument("--confirm", default=None)

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
    if args.command == "compile":
        comp_cmd = getattr(args, "compile_command", None)
        if comp_cmd is None:
            return _cmd_compile(args)
        if comp_cmd == "status":
            return _cmd_compile_status(args)
        if comp_cmd == "recover":
            return _cmd_compile_recover(args)
        parser.error(f"unknown compile command {comp_cmd!r}")
        return 2
    if args.command == "import":
        return _cmd_import(args)
    if args.command == "review":
        if getattr(args, "review_command", None) in (None,):
            return _cmd_review_loop(args)
        return {
            "list": _cmd_review_list,
            "show": _cmd_review_show,
            "categorize": _cmd_review_categorize,
            "auto-match": _cmd_review_auto_match,
            "approve": _cmd_review_approve,
            "reject": _cmd_review_reject,
            "reopen": _cmd_review_reopen,
        }[args.review_command](args)
    if args.command == "rule":
        return {
            "add": _cmd_rule_add, "list": _cmd_rule_list, "disable": _cmd_rule_disable,
        }[args.rule_command](args)
    if args.command == "fitid-trust":
        return _cmd_fitid_add(args) if args.fitid_command == "add" else _cmd_fitid_list(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


def _cmd_compile(args) -> int:
    if args.ledger_dir is None:
        print("error: the following arguments are required: --ledger-dir", file=sys.stderr)
        return 2
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(
                conn,
                action="compile",
                subject="compile",
                confirm=args.confirm,
                stdin_isatty=sys.stdin.isatty(),
                config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH

        try:
            summary = writer.compile_approved(conn, args.ledger_dir)
        except (CompileInputError, BeanCheckFailedError, BeanCheckUnavailableError, CompileError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_ERROR

        print(render.render_compile_summary(summary))
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_compile_status(args) -> int:
    conn = connect(str(args.db))
    try:
        latest_run = journal.get_latest_successful_run(conn)
        active_run = journal.get_active_started_run(conn)

        ledger_dir = Path(args.ledger_dir)
        year_files: list[str] = []
        txns_dir = ledger_dir / "txns"
        if txns_dir.exists():
            year_files = [f"txns/{p.name}" for p in txns_dir.glob("*.beancount")]

        has_files = (ledger_dir / "main.beancount").exists() or (ledger_dir / "accounts.beancount").exists() or bool(year_files)
        if has_files:
            on_disk_hash = hashing.compute_actual_output_hash(ledger_dir, year_files)
        else:
            on_disk_hash = "none"

        expected_hash = None
        if latest_run:
            expected_hash = latest_run.get("actual_output_hash") or latest_run.get("intended_output_hash")

        hash_matches = bool(expected_hash and on_disk_hash == expected_hash)

        status_data = {
            "latest_run": latest_run,
            "active_run": active_run,
            "on_disk_hash": on_disk_hash,
            "hash_matches": hash_matches,
        }
        print(render.render_compile_status(status_data, as_json=args.json))
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_compile_recover(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(
                conn,
                action="compile recover",
                subject="compile recover",
                confirm=args.confirm,
                stdin_isatty=sys.stdin.isatty(),
                config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH

        try:
            rec = recover.recover_dangling_compile(conn, args.ledger_dir)
        except CompileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_ERROR

        print(render.render_recovery_report(rec))
        return _EXIT_OK
    finally:
        conn.close()


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


def _cmd_review_show(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        row = conn.execute(
            "SELECT staged_transaction_id, proposed_date, status, payee, source_record_id, "
            " identity_method, identity_fingerprint FROM staged_transactions "
            "WHERE staged_transaction_id = ?", (args.staged_transaction_id,)
        ).fetchone()
        if row is None:
            print(f"error: unknown staged transaction {args.staged_transaction_id!r}", file=sys.stderr)
            return _EXIT_STATE
        (stx_id, proposed_date, status, payee, source_record_id,
         identity_method, identity_fingerprint) = row
        row_dict = {
            "staged_transaction_id": stx_id, "proposed_date": proposed_date, "status": status,
            "payee": payee, "source_record_id": source_record_id,
            "identity_method": identity_method, "identity_fingerprint": identity_fingerprint,
        }
        postings = [
            {"role": role, "account": account, "minor_units": mu, "currency": cur}
            for role, account, mu, cur in conn.execute(
                "SELECT role, account, minor_units, currency FROM staged_postings "
                "WHERE staged_transaction_id = ? ORDER BY posting_index", (stx_id,)
            )
        ]
        contra_account = next(
            (p["account"] for p in postings if p["role"] == "contra"), None
        )
        suggestion = None
        if contra_account is None:
            imported_account = next(
                (p["account"] for p in postings if p["role"] == "imported"), None
            )
            suggestion = resolve_rule(
                conn, canonical_payee(payee), imported_account, audit_skips=False
            )
        print(render.render_review_show(row_dict, postings, suggestion, as_json=args.json))
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_review_categorize(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_safe_mode_off(
                conn, action="review categorize", subject=args.staged_transaction_id,
                config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH

        rule_id = None
        if args.persist_rule:
            row = conn.execute(
                "SELECT payee FROM staged_transactions WHERE staged_transaction_id = ?",
                (args.staged_transaction_id,)
            ).fetchone()
            if row is None:
                print(f"error: unknown staged transaction {args.staged_transaction_id!r}", file=sys.stderr)
                return _EXIT_STATE
            imported_account = conn.execute(
                "SELECT account FROM staged_postings "
                "WHERE staged_transaction_id = ? AND role = 'imported'",
                (args.staged_transaction_id,)
            ).fetchone()[0]
            try:
                rule_id = rules_mod.persist_exact_rule(
                    conn, canonical_payee_value=canonical_payee(row[0]),
                    importing_account=imported_account, target_account=args.target_account,
                )
            except RuleExistsError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return _EXIT_STATE

        try:
            state.categorize(conn, args.staged_transaction_id, args.target_account, rule_id=rule_id)
        except ReviewStateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_STATE
        conn.commit()
        print(f"categorized {args.staged_transaction_id} -> {args.target_account}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_review_auto_match(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        subject = args.importing_account or "all"
        try:
            auth.require_operator(
                conn, action="review-auto-match", subject=subject, confirm=args.confirm,
                stdin_isatty=sys.stdin.isatty(), config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        matched, total = state.auto_match(conn, importing_account=args.importing_account)
        conn.commit()
        print(f"auto-matched {matched} of {total}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_review_approve(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(conn, action="review-approve", subject=args.staged_transaction_id,
                                  confirm=args.confirm, stdin_isatty=sys.stdin.isatty(),
                                  config_dir=args.config_dir)
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        try:
            state.approve(conn, args.staged_transaction_id)
            conn.commit()
        except ReviewStateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_STATE
        except ApproveGateError as exc:
            append_audit_event(conn, actor="operator",
                               action=f"review approve (denied: {exc.reason})",
                               target=args.staged_transaction_id, result="denied")
            conn.commit()
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        print(f"approved {args.staged_transaction_id}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_review_reject(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(conn, action="review-reject", subject=args.staged_transaction_id,
                                  confirm=args.confirm, stdin_isatty=sys.stdin.isatty(),
                                  config_dir=args.config_dir)
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        try:
            state.reject(conn, args.staged_transaction_id, reason=args.reason)
        except ReviewStateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_STATE
        conn.commit()
        print(f"rejected {args.staged_transaction_id}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_review_reopen(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(conn, action="review-reopen", subject=args.staged_transaction_id,
                                  confirm=args.confirm, stdin_isatty=sys.stdin.isatty(),
                                  config_dir=args.config_dir)
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        try:
            state.reopen(conn, args.staged_transaction_id)
        except ReviewStateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_STATE
        conn.commit()
        print(f"reopened {args.staged_transaction_id}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_review_loop(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        db_basename = Path(args.db).name
        try:
            auth.require_safe_mode_off(
                conn, action="review-session", subject=db_basename, config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        try:
            run_review_loop(
                conn, stdin=sys.stdin, stdout=sys.stdout, db_basename=db_basename,
                confirm=args.confirm, stdin_isatty=sys.stdin.isatty(),
                config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_rule_add(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(conn, action="rule-add", subject=args.account,
                                  confirm=args.confirm, stdin_isatty=sys.stdin.isatty(),
                                  config_dir=args.config_dir)
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        try:
            rule_id = rules_mod.add_rule(
                conn, match_type=args.match_type, pattern=args.pattern,
                target_account=args.account, importing_account=args.importing_account,
                priority=args.priority,
            )
        except RuleError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_STATE
        conn.commit()
        print(f"added {rule_id}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_rule_list(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        print(render.render_rule_list(rules_mod.list_rules(conn), as_json=args.json))
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_rule_disable(args) -> int:
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(conn, action="rule-disable", subject=args.rule_id,
                                  confirm=args.confirm, stdin_isatty=sys.stdin.isatty(),
                                  config_dir=args.config_dir)
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH
        try:
            rules_mod.disable_rule(conn, args.rule_id)
        except RuleError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_STATE
        conn.commit()
        print(f"disabled {args.rule_id}")
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
