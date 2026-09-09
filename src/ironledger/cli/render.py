"""Human-readable and JSON rendering for CLI output."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ironledger.compile.recover import RecoveryDecision
from ironledger.compile.writer import CompileSummary
from ironledger.project.query import BalanceRow, SearchHit

__all__ = [
    "render_import_result",
    "render_staged_list",
    "render_fitid_list",
    "render_review_show",
    "render_rule_list",
    "render_compile_summary",
    "render_compile_status",
    "render_recovery_report",
    "render_search_hits",
    "render_balances",
    "render_project_status",
]


def render_import_result(result, mechanism: str) -> str:
    lines = [
        f"import ok ({mechanism}): document {result.source_document_id[:12]}, "
        f"{result.records_created} new staged transaction(s)"
        + (", nothing to do" if result.short_circuited else "")
    ]
    lines.extend(result.advisories)
    return "\n".join(lines)


def render_staged_list(rows: list[dict], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(rows, indent=2, sort_keys=True)
    if not rows:
        return "no staged transactions"
    out = []
    for r in rows:
        out.append(
            f"{r['staged_transaction_id'][:16]}  {r['proposed_date']}  {r['status']:9}  "
            f"{r['payee']}  [{r['posting_summary']}]"
        )
    return "\n".join(out)


def render_fitid_list(rows: list[dict], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(rows, indent=2, sort_keys=True)
    if not rows:
        return "no FITID trust records"
    return "\n".join(f"{r['institution_id']}/{r['account_id']}  added {r['added_at_utc']}" for r in rows)


def render_review_show(row: dict, postings: list[dict], suggestion, *, as_json: bool) -> str:
    if as_json:
        return json.dumps(
            {**row, "postings": postings, "rule_suggestion": suggestion},
            indent=2, sort_keys=True,
        )
    lines = [
        f"{row['staged_transaction_id']}  {row['proposed_date']}  {row['status']}",
        f"  payee     {row['payee']}",
        f"  identity  {row['identity_method']} {row['identity_fingerprint'][:12]}",
        f"  source    {row['source_record_id']}",
    ]
    for p in postings:
        lines.append(f"  {p['role']:8} {p['account'] or '<uncategorized>':30} {p['minor_units']:>12} {p['currency']}")
    if suggestion:
        lines.append(f"  rule suggests: {suggestion}")
    return "\n".join(lines)


def render_rule_list(rows: list[dict], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(rows, indent=2, sort_keys=True)
    if not rows:
        return "no categorization rules"
    return "\n".join(
        f"{r['rule_id']}  {r['match_type']} {r['pattern']!r} -> {r['target_account']}  "
        f"prio {r['priority']}  {'active' if r['active'] else 'disabled'}"
        + (f"  scope {r['importing_account']}" if r['importing_account'] else "")
        for r in rows
    )


def render_compile_summary(summary: CompileSummary, next_project_cmd: str | None = None) -> str:
    lines = [
        f"Compile run {summary.compile_run_id} succeeded:",
        f"  Entries compiled: {summary.entry_count} entries",
        f"  Year files: {', '.join(summary.year_files) if summary.year_files else 'none'}",
        f"  Output SHA-256: {summary.output_hash}",
    ]
    if next_project_cmd:
        lines.append("")
        lines.append(next_project_cmd)
    return "\n".join(lines)


def render_recovery_report(rec: RecoveryDecision) -> str:
    if rec.action == "none":
        return "No dangling compile run to recover."
    if rec.action == "recovered":
        return f"Recovered compile run {rec.compile_run_id}: {rec.detail}"
    return f"Recovery [{rec.action}]: {rec.compile_run_id} - {rec.detail}"


def render_compile_status(status_data: dict[str, Any], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(status_data, indent=2, sort_keys=True)

    lines = ["Compile Status:"]
    latest = status_data.get("latest_run")
    if latest:
        lines.append(
            f"  Latest Run: {latest['compile_run_id']} ({latest['status']}) at "
            f"{latest.get('finished_at_utc') or latest.get('started_at_utc')}"
        )
        lines.append(
            f"  Expected Hash: {latest.get('actual_output_hash') or latest.get('intended_output_hash')}"
        )
    else:
        lines.append("  Latest Run: none")

    active = status_data.get("active_run")
    if active:
        lines.append(f"  Active Started Run: {active['compile_run_id']} (requires 'compile recover')")

    lines.append(f"  On-Disk Hash:  {status_data.get('on_disk_hash', 'none')}")
    lines.append(f"  Hash Matches:  {'YES' if status_data.get('hash_matches') else 'NO'}")
    return "\n".join(lines)


def render_search_hits(hits: list[SearchHit], *, as_json: bool) -> str:
    if as_json:
        return json.dumps([asdict(h) for h in hits], indent=2, sort_keys=True)
    return "\n".join(
        f"{h.entry_date}  {h.payee}  {h.narration}  {h.account}  "
        f"{h.minor_units}  {h.currency}  {h.staged_transaction_id}"
        for h in hits
    )


def render_balances(rows: list[BalanceRow], *, as_json: bool) -> str:
    if as_json:
        return json.dumps([asdict(r) for r in rows], indent=2, sort_keys=True)
    return "\n".join(f"{r.account}  {r.minor_units}  {r.currency}" for r in rows)


def render_project_status(status_data: dict[str, Any], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(status_data, indent=2, sort_keys=True)
    if status_data.get("status") == "missing":
        return "nothing built yet"

    lines = [f"Project status: {status_data.get('status', 'unknown')}"]
    if "ledger_output_hash" in status_data:
        lines.append(f"  Ledger output hash: {status_data['ledger_output_hash']}")
    lines.append(
        f"  Hash matches files: {'YES' if status_data.get('hash_matches_files') else 'NO'}"
    )
    if "hash_matches_compile" in status_data:
        lines.append(
            f"  Hash matches compile: {'YES' if status_data['hash_matches_compile'] else 'NO'}"
        )
    if "latest_run" in status_data:
        latest = status_data["latest_run"]
        if latest:
            lines.append(
                f"  Latest compile: {latest.get('compile_run_id')} ({latest.get('status')})"
            )
        else:
            lines.append("  Latest compile: none")
    return "\n".join(lines)
