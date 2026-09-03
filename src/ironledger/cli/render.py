"""Human-readable and JSON rendering for CLI output."""

from __future__ import annotations

import json

__all__ = ["render_import_result", "render_staged_list", "render_fitid_list"]


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
