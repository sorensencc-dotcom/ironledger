"""Human-readable and JSON rendering for CLI output."""

from __future__ import annotations

import json

__all__ = ["render_import_result", "render_staged_list", "render_fitid_list", "render_review_show", "render_rule_list"]


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
