"""`ironledger` command tree (Phase 5)."""

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
from ironledger.compile.errors import (
    BeanCheckFailedError,
    BeanCheckUnavailableError,
    CompileError,
    CompileInputError,
    CompileLockedError,
)
from ironledger.compile import hashing, journal, recover, writer
from ironledger.project.activate import default_projection_dir, rebuild_projection
from ironledger.project.errors import ProjectError
from ironledger.project.query import assert_fresh, balances as project_balances, projection_status, search as project_search
from ironledger.mcp.bind import assert_loopback
from ironledger.mcp.errors import McpBindError
from ironledger.mcp.http import serve_http
from ironledger.mcp.stdio import run_stdio

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2
_EXIT_AUTH = 3
_EXIT_INGEST = 4
_EXIT_STATE = 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ironledger",
        epilog=(
            "Golden path (from the repo root, after compile has succeeded):\n"
            "  python -m ironledger.cli project --db ironledger.db --ledger-dir ledger "
            '--confirm "authorize project"\n'
            "  python -m ironledger.cli search --ledger-dir ledger coffee\n"
            "  python -m ironledger.cli balances --ledger-dir ledger"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", required=False, default=None, help="path to the SQLite ledger index")
    parser.add_argument("--ledger-dir", dest="parent_ledger_dir", default=None, type=Path)
    parser.add_argument("--config-dir", default="config", type=Path)
    parser.add_argument("--evidence-dir", default="evidence", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    # compile command tree
    comp = sub.add_parser("compile", help="compile approved staged transactions into Beancount ledger")
    comp.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the output ledger directory")
    comp.add_argument("--confirm", default=None, help="confirmation phrase for operator authorization")
    comp_sub = comp.add_subparsers(dest="compile_command", required=False)

    comp_status = comp_sub.add_parser("status", help="show status of ledger compilation and crash recovery")
    comp_status.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the output ledger directory")
    comp_status.add_argument("--json", action="store_true", help="render status as JSON")

    comp_recover = comp_sub.add_parser("recover", help="recover an interrupted compile run")
    comp_recover.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the output ledger directory")
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

    proj = sub.add_parser("project", help="rebuild the analytics projection from compiled ledger files")
    proj.add_argument(
        "--db",
        required=False,
        default=argparse.SUPPRESS,
        help="path to the SQLite ledger index",
    )
    proj.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the compiled ledger directory")
    proj.add_argument("--projection-dir", default=None, type=Path, help="path to the projection directory")
    proj.add_argument("--confirm", default=None, help="confirmation phrase for operator authorization")
    proj_sub = proj.add_subparsers(dest="project_command", required=False)

    proj_status = proj_sub.add_parser("status", help="show projection freshness and compile comparison")
    proj_status.add_argument(
        "--db",
        required=False,
        default=argparse.SUPPRESS,
        help="path to the SQLite ledger index",
    )
    proj_status.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the compiled ledger directory")
    proj_status.add_argument("--projection-dir", default=None, type=Path, help="path to the projection directory")
    proj_status.add_argument("--json", action="store_true", help="render status as JSON")

    srch = sub.add_parser("search", help="search the live projection")
    srch.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the compiled ledger directory")
    srch.add_argument("--projection-dir", default=None, type=Path, help="path to the projection directory")
    srch.add_argument("--json", action="store_true", help="render hits as JSON")
    srch.add_argument("--limit", type=int, default=50)
    srch.add_argument("--offset", type=int, default=0)
    srch.add_argument("query")

    bal = sub.add_parser("balances", help="show projection account balances")
    bal.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the compiled ledger directory")
    bal.add_argument("--projection-dir", default=None, type=Path, help="path to the projection directory")
    bal.add_argument("--json", action="store_true", help="render balances as JSON")

    mcp = sub.add_parser("mcp", help="run the read-only MCP server (stdio or loopback HTTP)")
    mcp.add_argument("--db", required=False, default=argparse.SUPPRESS, help="path to the SQLite ledger index")
    mcp.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the compiled ledger directory")
    mcp.add_argument("--projection-dir", default=None, type=Path, help="path to the projection directory")
    mcp.add_argument("--bind", default=None, help="loopback IP to bind for Streamable HTTP (127.0.0.1 or ::1)")
    mcp.add_argument("--port", type=int, default=None, help="port to listen on for Streamable HTTP (1..65535)")
    mcp.add_argument("--rotate-token", action="store_true", help="rotate bearer token before listen")

    web = sub.add_parser("web", help="launch the Operator Workbench web interface")
    web.add_argument("--db", default=argparse.SUPPRESS, help="path to the SQLite ledger index")
    web.add_argument("--host", default="127.0.0.1", help="host address to bind")
    web.add_argument("--port", type=int, default=8000, help="port number to bind")
    web.add_argument("--projection-db", default=None, help="path to projection SQLite database")
    web.add_argument("--open-browser", action="store_true", help="open browser on startup")
    web.add_argument("--reload", action="store_true", help="enable auto-reload on code changes")

    sync_parser = sub.add_parser("sync", help="SimpleFIN bank synchronization")
    sync_parser.add_argument("--db", default=argparse.SUPPRESS, help="path to the SQLite ledger index")
    sync_sub = sync_parser.add_subparsers(dest="sync_command")
    sync_auth = sync_sub.add_parser("auth", help="Credential management")
    sync_auth_sub = sync_auth.add_subparsers(dest="sync_auth_command")
    sync_auth_claim = sync_auth_sub.add_parser("claim", help="Claim a SimpleFIN setup token")
    sync_auth_claim.add_argument("--stdin", action="store_true", help="Read token from stdin")
    sync_auth_sub.add_parser("status", help="Show masked connection info")
    sync_poll = sync_sub.add_parser("poll", help="Run a sync poll")
    sync_poll.add_argument("--lookback", type=int, default=30, help="Days to fetch (default: 30)")
    sync_poll.add_argument("--dry-run", action="store_true", help="Parse without staging")
    sync_accounts = sync_sub.add_parser("accounts", help="Account mapping")
    sync_accounts_sub = sync_accounts.add_subparsers(dest="sync_accounts_command")
    sync_accounts_sub.add_parser("list", help="List account mappings")

    # compliance command tree
    comp_p = sub.add_parser("compliance", help="compliance audit archive bundles (SOC2, ISO27001, SOX)")
    comp_p.add_argument("--db", default=argparse.SUPPRESS, help="path to SQLite ledger index")
    comp_sub = comp_p.add_subparsers(dest="compliance_command", required=True)
    comp_gen = comp_sub.add_parser("generate", help="generate a sealed compliance audit bundle")
    comp_gen.add_argument("--ledger-id", required=True, help="ledger identifier")
    comp_gen.add_argument("--framework", required=True, choices=["SOC2_TYPE2", "ISO27001", "SOX", "CUSTOM"], help="compliance framework")
    comp_gen.add_argument("--start", required=True, help="period start UTC timestamp (ISO-8601)")
    comp_gen.add_argument("--end", required=True, help="period end UTC timestamp (ISO-8601)")
    comp_gen.add_argument("--output-dir", default=None, help="directory to write sealed archive file")

    comp_ver = comp_sub.add_parser("verify", help="cryptographically verify a sealed compliance archive")
    comp_ver.add_argument("--archive", required=True, help="path to .tar archive file")
    comp_ver.add_argument("--expected-root", default=None, help="expected Merkle root hex")
    comp_ver.add_argument("--expected-sha", default=None, help="expected archive SHA-256")

    # anomaly command tree
    anom_p = sub.add_parser("anomaly", help="pure rational anomaly and fraud detection")
    anom_p.add_argument("--db", default=argparse.SUPPRESS, help="path to SQLite ledger index")
    anom_sub = anom_p.add_subparsers(dest="anomaly_command", required=True)
    anom_scan = anom_sub.add_parser("scan", help="scan staged transactions for anomalies")
    anom_scan.add_argument("--ledger-id", required=True, help="ledger identifier")

    anom_list = anom_sub.add_parser("list", help="list anomaly flags")
    anom_list.add_argument("--ledger-id", required=True, help="ledger identifier")
    anom_list.add_argument("--status", default=None, help="filter by resolution status (OPEN, RESOLVED, DISMISSED, etc.)")

    anom_res = anom_sub.add_parser("resolve", help="atomically resolve an anomaly flag")
    anom_res.add_argument("--ledger-id", required=True, help="ledger identifier")
    anom_res.add_argument("--flag-id", required=True, help="flag identifier")
    anom_res.add_argument("--status", required=True, choices=["CONFIRMED_FRAUD", "RESOLVED_VALID", "DISMISSED"], help="resolution status")
    anom_res.add_argument("--actor", default="operator", help="actor name")
    anom_res.add_argument("--reason", default="", help="resolution reason")

    # federation command tree
    fed_p = sub.add_parser("federation", help="multi-tenant federation and event outbox governance")
    fed_p.add_argument("--db", default=argparse.SUPPRESS, help="path to SQLite ledger index")
    fed_sub = fed_p.add_subparsers(dest="federation_command", required=True)

    fed_nodes = fed_sub.add_parser("nodes", help="manage cluster nodes")
    fed_nodes_sub = fed_nodes.add_subparsers(dest="nodes_command", required=True)
    fed_nodes_sub.add_parser("list", help="list cluster nodes")

    fed_outbox = fed_sub.add_parser("outbox", help="manage federated event outbox")
    fed_outbox_sub = fed_outbox.add_subparsers(dest="outbox_command", required=True)
    fed_outbox_list = fed_outbox_sub.add_parser("list", help="list pending outbox events")
    fed_outbox_list.add_argument("--tenant-id", default=None, help="filter by tenant identifier")
    fed_outbox_list.add_argument("--limit", type=int, default=50, help="maximum events to list")

    fed_outbox_disp = fed_outbox_sub.add_parser("dispatch", help="dispatch pending federated outbox events")
    fed_outbox_disp.add_argument("--worker-id", default="cli-worker", help="worker identifier for lease fencing")
    fed_outbox_disp.add_argument("--batch-size", type=int, default=50, help="maximum events to process in batch")


    # failover command tree
    fail_p = sub.add_parser("failover", help="high-availability primary election and cluster failover")
    fail_p.add_argument("--db", default=argparse.SUPPRESS, help="path to SQLite ledger index")
    fail_sub = fail_p.add_subparsers(dest="failover_command", required=True)

    fail_stat = fail_sub.add_parser("status", help="show cluster failover and quorum status")
    fail_stat.add_argument("--cluster-id", default="default", help="cluster identifier")

    fail_prom = fail_sub.add_parser("promote", help="promote node to cluster PRIMARY")
    fail_prom.add_argument("--cluster-id", required=True, help="cluster identifier")
    fail_prom.add_argument("--candidate-node-id", required=True, help="node identifier to promote")
    fail_prom.add_argument("--lease-seconds", type=int, default=15, help="lease duration in seconds")

    # security command tree
    sec_p = sub.add_parser("security", help="tenant key rotation and cryptographic vault management")
    sec_p.add_argument("--db", default=argparse.SUPPRESS, help="path to SQLite ledger index")
    sec_sub = sec_p.add_subparsers(dest="security_command", required=True)

    sec_rot = sec_sub.add_parser("rotate-key", help="rotate tenant KEK and re-wrap stored secrets")
    sec_rot.add_argument("--tenant-id", required=True, help="tenant identifier")
    sec_rot.add_argument("--new-kek-key-id", required=True, help="new KEK identifier")
    sec_rot.add_argument("--rotated-by", default="operator", help="operator or service name")

    # prices command tree
    prices_parser = sub.add_parser("prices", help="commodity and currency price feed management")
    prices_parser.add_argument("--db", default=argparse.SUPPRESS, help="path to the SQLite ledger index")
    prices_parser.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the ledger directory")
    prices_parser.add_argument("--config-dir", default="config", type=Path, help="path to the config directory")
    prices_sub = prices_parser.add_subparsers(dest="prices_command", required=True)
    prices_poll = prices_sub.add_parser("poll", help="poll price feeds and sync prices.beancount and price_history")
    prices_poll.add_argument("--db", default=argparse.SUPPRESS, help="path to the SQLite ledger index")
    prices_poll.add_argument("--ledger-dir", dest="ledger_dir", default=None, type=Path, help="path to the ledger directory")
    prices_poll.add_argument("--config-dir", default="config", type=Path, help="path to the config directory")
    prices_poll.add_argument("--symbols", nargs="*", default=None, help="specific symbols to fetch (e.g. AAPL BTC)")
    prices_poll.add_argument("--quote-currency", default="USD", help="quote currency (default: USD)")
    prices_poll.add_argument("--json", action="store_true", help="output result as JSON")

    return parser





def _require_db(args) -> bool:
    if not args.db:
        print("error: the following arguments are required: --db", file=sys.stderr)
        return False
    return True


def _require_ledger_dir(args) -> Path | None:
    ledger_dir = getattr(args, "ledger_dir", None) or getattr(args, "parent_ledger_dir", None)
    if ledger_dir is None:
        print("error: the following arguments are required: --ledger-dir", file=sys.stderr)
        return None
    return Path(ledger_dir)


def _projection_dir(args, ledger_dir: Path) -> Path:
    override = getattr(args, "projection_dir", None)
    return Path(override) if override is not None else default_projection_dir(ledger_dir)


def _needs_operational_db(args) -> bool:
    if args.command in {"compile", "import", "review", "rule", "fitid-trust", "mcp"}:
        return True
    if args.command == "project" and getattr(args, "project_command", None) is None:
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if _needs_operational_db(args) and not _require_db(args):
        return 2
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
    if args.command == "project":
        proj_cmd = getattr(args, "project_command", None)
        if proj_cmd is None:
            return _cmd_project(args)
        if proj_cmd == "status":
            return _cmd_project_status(args)
        parser.error(f"unknown project command {proj_cmd!r}")
        return 2
    if args.command == "search":
        return _cmd_search(args)
    if args.command == "balances":
        return _cmd_balances(args)
    if args.command == "mcp":
        return _cmd_mcp(args)
    if args.command == "web":
        return _cmd_web(args)
    if args.command == "sync":
        if not getattr(args, "sync_command", None):
            for action in parser._actions:
                if getattr(action, "choices", None) and "sync" in action.choices:
                    action.choices["sync"].print_help()
                    break
            return _EXIT_USAGE
        return _cmd_sync(args)
    if args.command == "compliance":
        return _cmd_compliance(args)
    if args.command == "anomaly":
        return _cmd_anomaly(args)
    if args.command == "federation":
        return _cmd_federation(args)
    if args.command == "failover":
        return _cmd_failover(args)
    if args.command == "security":
        return _cmd_security(args)
    if args.command == "prices":
        return _cmd_prices(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


def _cmd_prices(args) -> int:
    import json
    from pathlib import Path
    from ironledger.prices.scraper_daemon import PriceScraperDaemon
    from ironledger.prices.router import PriceCascadeRouter, create_default_price_router
    from ironledger.prices.providers.manual import ManualProvider
    from ironledger.governance.migrations import migrate_governed

    db_path = getattr(args, "db", None) or "ironledger.db"
    conn = connect(db_path)
    try:
        migrate_governed(conn, db_path)
    finally:
        conn.close()

    ledger_dir = Path(getattr(args, "ledger_dir", None) or Path(db_path).parent / "ledger")
    prices_beancount = ledger_dir / "prices.beancount"
    config_dir = Path(getattr(args, "config_dir", None) or "config")
    config_path = config_dir / "prices.json"

    manual_quotes = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
                manual_quotes = cfg_data.get("manual_quotes", {})
        except Exception:
            pass

    router = create_default_price_router(manual_quotes=manual_quotes)
    daemon = PriceScraperDaemon(
        db_path=Path(db_path),
        prices_ledger_path=prices_beancount,
        router=router,
        ledger_id="default",
    )


    if args.prices_command == "poll":
        symbols_arg = None
        if args.symbols:
            symbols_arg = [(s, args.quote_currency) for s in args.symbols]
        res = daemon.sync_watchlist(symbols=symbols_arg, config_path=config_path if not symbols_arg else None)
        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            print(f"Price sync status: {res.get('status')} (synced: {res.get('synced_count', 0)}, failed: {res.get('failed_count', 0)})")
            if res.get("failed_symbols"):
                for f in res["failed_symbols"]:
                    print(f"  Warning: {f}", file=sys.stderr)
        return _EXIT_OK if res.get("status") in ("success", "partial_failure") else _EXIT_ERROR
    return _EXIT_USAGE


def _cmd_failover(args) -> int:
    from ironledger.cli.commands.failover import (
        run_failover_promote,
        run_failover_status,
    )

    db_path = getattr(args, "db", None) or "ironledger.db"
    if args.failover_command == "status":
        return run_failover_status(db_path=db_path, cluster_id=args.cluster_id)
    elif args.failover_command == "promote":
        return run_failover_promote(
            db_path=db_path,
            cluster_id=args.cluster_id,
            candidate_node_id=args.candidate_node_id,
            lease_seconds=args.lease_seconds,
        )
    return 2


def _cmd_security(args) -> int:
    from ironledger.cli.commands.failover import run_security_rotate_key

    db_path = getattr(args, "db", None) or "ironledger.db"
    if args.security_command == "rotate-key":
        return run_security_rotate_key(
            db_path=db_path,
            tenant_id=args.tenant_id,
            new_kek_key_id=args.new_kek_key_id,
            rotated_by=args.rotated_by,
        )
    return 2


def _cmd_federation(args) -> int:
    from ironledger.cli.commands.federation import (
        run_federation_nodes_list,
        run_federation_outbox_dispatch,
        run_federation_outbox_list,
    )

    db_path = getattr(args, "db", None) or "ironledger.db"
    if args.federation_command == "nodes":
        if args.nodes_command == "list":
            return run_federation_nodes_list(db_path=db_path)
    elif args.federation_command == "outbox":
        if args.outbox_command == "list":
            return run_federation_outbox_list(
                db_path=db_path,
                tenant_id=args.tenant_id,
                limit=args.limit,
            )
        elif args.outbox_command == "dispatch":
            return run_federation_outbox_dispatch(
                db_path=db_path,
                worker_id=args.worker_id,
                batch_size=args.batch_size,
            )
    return 2




def _cmd_compliance(args) -> int:
    from ironledger.cli.commands.compliance import run_compliance_generate, run_compliance_verify

    db_path = getattr(args, "db", None) or "ironledger.db"
    if args.compliance_command == "generate":
        return run_compliance_generate(
            db_path=db_path,
            ledger_id=args.ledger_id,
            framework=args.framework,
            period_start_utc=args.start,
            period_end_utc=args.end,
            output_dir=args.output_dir,
        )
    elif args.compliance_command == "verify":
        return run_compliance_verify(
            archive_path=args.archive,
            expected_root=args.expected_root,
            expected_sha=args.expected_sha,
        )
    return 2


def _cmd_anomaly(args) -> int:
    from ironledger.cli.commands.anomaly import run_anomaly_list, run_anomaly_resolve, run_anomaly_scan

    db_path = getattr(args, "db", None) or "ironledger.db"
    if args.anomaly_command == "scan":
        return run_anomaly_scan(db_path=db_path, ledger_id=args.ledger_id)
    elif args.anomaly_command == "list":
        return run_anomaly_list(db_path=db_path, ledger_id=args.ledger_id, status=args.status)
    elif args.anomaly_command == "resolve":
        return run_anomaly_resolve(
            db_path=db_path,
            ledger_id=args.ledger_id,
            flag_id=args.flag_id,
            status=args.status,
            actor=args.actor,
            reason=args.reason,
        )
    return 2



def _cmd_web(args) -> int:
    from ironledger.cli.commands.web import run_web

    db_path = args.db or "ironledger.db"
    run_web(
        db_path=db_path,
        projection_db_path=args.projection_db,
        config_dir=args.config_dir,
        host=args.host,
        port=args.port,
        open_browser=args.open_browser,
        reload=args.reload,
    )
    return _EXIT_OK


def _cmd_sync(args) -> int:
    if not getattr(args, "sync_command", None):
        return _EXIT_USAGE
    import getpass
    from ironledger.security.secrets import (
        claim_setup_token, get_access_url, mask_access_url, CredentialsNotFoundError,
    )
    db_path = getattr(args, "db", None) or "ironledger.db"
    conn = connect(db_path)
    try:
        migrations.migrate_governed(conn, db_path)
        if args.sync_command == "auth":
            if args.sync_auth_command == "claim":
                token = sys.stdin.readline().strip() if args.stdin else getpass.getpass("SimpleFIN setup token: ")
                masked = claim_setup_token(token, conn)
                print(f"Access URL stored: {masked}")
            elif args.sync_auth_command == "status":
                try:
                    print(f"Connected: {mask_access_url(get_access_url(conn))}")
                except CredentialsNotFoundError:
                    print("No credentials stored. Run: ironledger sync auth claim")
        elif args.sync_command == "poll":
            from datetime import datetime, timezone, timedelta
            from pathlib import Path
            from ironledger.pipeline.sync_daemon import acquire_lock, release_lock
            from ironledger.ingest.formats.simplefin import fetch_accounts
            from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload
            lock_path = Path(db_path).parent / ".sync.lock"
            lock_token = acquire_lock(lock_path)
            try:
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(days=args.lookback)
                ev_dir = Path(db_path).parent / "evidence" / "source_documents"
                payload = fetch_accounts(conn, start_date=start_dt, end_date=end_dt, evidence_dir=ev_dir)
                if args.dry_run:
                    import json as _json
                    print(_json.dumps(payload, indent=2))
                else:
                    account_map = dict(
                        conn.execute("SELECT remote_account_id, canonical_account FROM simplefin_account_map").fetchall()
                    )
                    ins, skip = ingest_simplefin_payload(conn, payload, evidence_path=ev_dir, account_map=account_map)
                    print(f"Sync: {ins} inserted, {skip} skipped")
            finally:
                release_lock(lock_path, token=lock_token)
        elif args.sync_command == "accounts" and args.sync_accounts_command == "list":
            for r in conn.execute("SELECT remote_account_id, canonical_account FROM simplefin_account_map").fetchall():
                print(f"  {r[0]} -> {r[1]}")
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_compile(args) -> int:
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
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
            summary = writer.compile_approved(conn, ledger_dir)
        except CompileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_ERROR

        next_cmd = (
            f"python -m ironledger.cli project --db {args.db} --ledger-dir {ledger_dir} "
            f'--confirm "{auth.PROJECT_PHRASE}"'
        )
        print(render.render_compile_summary(summary, next_project_cmd=next_cmd))
        return _EXIT_OK
    finally:
        conn.close()


def _cmd_compile_status(args) -> int:
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
        return 2
    conn = connect(str(args.db))
    try:
        latest_run = journal.get_latest_successful_run(conn)
        active_run = journal.get_active_started_run(conn)
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
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
        return 2
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
            rec = recover.recover_dangling_compile(conn, ledger_dir)
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


def _cmd_project(args) -> int:
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
        return 2
    projection_dir = _projection_dir(args, ledger_dir)
    conn = connect(str(args.db))
    try:
        migrations.migrate(conn)
        try:
            auth.require_operator(
                conn,
                action="project",
                subject="project",
                confirm=args.confirm,
                stdin_isatty=sys.stdin.isatty(),
                config_dir=args.config_dir,
            )
        except AuthorizationError as exc:
            print(f"denied: {exc}", file=sys.stderr)
            return _EXIT_AUTH

        try:
            summary = rebuild_projection(conn, ledger_dir, projection_dir)
        except (ProjectError, CompileLockedError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_ERROR

        print(
            f"Projection rebuilt: {summary.entry_count} entries, "
            f"{summary.posting_count} postings, hash {summary.ledger_output_hash}"
        )
        return _EXIT_OK
    finally:
        conn.close()




def _cmd_project_status(args) -> int:
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
        return 2
    projection_dir = _projection_dir(args, ledger_dir)
    as_json = bool(getattr(args, "json", False))
    status_data = projection_status(ledger_dir, projection_dir, db=args.db)
    print(render.render_project_status(status_data, as_json=as_json))
    return _EXIT_OK


def _cmd_search(args) -> int:
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
        return 2
    projection_dir = _projection_dir(args, ledger_dir)
    try:
        conn = assert_fresh(ledger_dir, projection_dir, db=args.db)
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    try:
        hits = project_search(conn, args.query, limit=args.limit, offset=args.offset)
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    finally:
        conn.close()
    print(render.render_search_hits(hits, as_json=args.json))
    return _EXIT_OK


def _cmd_balances(args) -> int:
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
        return 2
    projection_dir = _projection_dir(args, ledger_dir)
    try:
        conn = assert_fresh(ledger_dir, projection_dir, db=args.db)
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    try:
        rows = project_balances(conn)
    finally:
        conn.close()
    print(render.render_balances(rows, as_json=args.json))
    return _EXIT_OK


def _cmd_mcp(args) -> int:
    ledger_dir = _require_ledger_dir(args)
    if ledger_dir is None:
        return 2
    projection_dir = _projection_dir(args, ledger_dir)

    bind = getattr(args, "bind", None)
    port = getattr(args, "port", None)
    rotate = bool(getattr(args, "rotate_token", False))

    if bind is None and port is not None:
        print("error: --port requires --bind", file=sys.stderr)
        return 2
    if bind is not None and port is None:
        print("error: --bind requires --port", file=sys.stderr)
        return 2
    if rotate and bind is None:
        print("error: --rotate-token requires --bind", file=sys.stderr)
        return 2

    if bind is not None:
        try:
            assert_loopback(bind)
        except McpBindError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if port < 1 or port > 65535:
            print(f"error: port must be between 1 and 65535, got {port}", file=sys.stderr)
            return 2
        server = serve_http(
            host=bind,
            port=port,
            ledger_dir=ledger_dir,
            projection_dir=projection_dir,
            db=args.db,
            rotate=rotate,
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0

    return run_stdio(
        sys.stdin.buffer,
        sys.stdout.buffer,
        sys.stderr,
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=args.db,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
