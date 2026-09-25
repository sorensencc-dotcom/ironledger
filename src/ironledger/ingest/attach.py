"""Propose attaching a later source row to an existing staged event."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from datetime import date

from ironledger.ingest.stage import StagedInput
from ironledger.ingest.identity import canonical_payee

__all__ = ["assign_proposals"]

_MATCH_STATUSES = ("pending", "categorized", "approved")
_PAYEE_TOKEN = re.compile(r"[a-z0-9]+")


def assign_proposals(
    conn: sqlite3.Connection,
    *,
    source_document_id: str,
    rows: tuple[tuple[StagedInput, int], ...],
    now_utc: str,
) -> list[str]:
    """Write pending attach_proposals for rows that match existing imported legs.

    Returns proposal ids created this call. Never inserts staged_transactions.
    One proposal per source_record_id. Events already listed on a pending
    proposal from this document are not offered to a later row.
    """
    claimed = _claimed_events(conn, source_document_id)
    created: list[str] = []
    for staged, window_days in rows:
        existing = conn.execute(
            "SELECT proposal_id FROM attach_proposals WHERE source_record_id = ?",
            (staged.source_record_id,),
        ).fetchone()
        if existing is not None:
            continue
        exact, near = _classify(conn, staged, window_days)
        exact = [sid for sid in exact if sid not in claimed]
        near = [sid for sid in near if sid not in claimed]
        if exact:
            kind = "unique" if len(exact) == 1 else "ambiguous"
            candidates = exact
        elif near:
            kind = "near_miss"
            candidates = near
        else:
            continue
        proposal_id = f"ap:{staged.source_record_id}"
        payload = asdict(staged)
        conn.execute(
            "INSERT INTO attach_proposals ("
            " proposal_id, source_record_id, source_document_id, kind, "
            " candidate_staged_ids, staged_input_json, status, created_at_utc"
            ") VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                proposal_id,
                staged.source_record_id,
                source_document_id,
                kind,
                json.dumps(candidates),
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                now_utc,
            ),
        )
        claimed.update(candidates)
        created.append(proposal_id)
    return created


def _claimed_events(conn: sqlite3.Connection, source_document_id: str) -> set[str]:
    claimed: set[str] = set()
    rows = conn.execute(
        "SELECT candidate_staged_ids FROM attach_proposals "
        "WHERE source_document_id = ? AND status = 'pending'",
        (source_document_id,),
    )
    for (raw,) in rows:
        claimed.update(json.loads(raw))
    return claimed


def _classify(
    conn: sqlite3.Connection, staged: StagedInput, window_days: int
) -> tuple[list[str], list[str]]:
    target = date.fromisoformat(staged.iso_date)
    flipped = -staged.minor_units
    rows = conn.execute(
        "SELECT st.staged_transaction_id, st.proposed_date, sp.minor_units, st.payee "
        "FROM staged_transactions st "
        "JOIN staged_postings sp ON sp.staged_transaction_id = st.staged_transaction_id "
        "WHERE sp.role = 'imported' AND sp.account = ? AND sp.currency = ? "
        "AND st.status IN (?, ?, ?) "
        "AND (sp.minor_units = ? OR sp.minor_units = ?)",
        (
            staged.account,
            staged.currency,
            _MATCH_STATUSES[0],
            _MATCH_STATUSES[1],
            _MATCH_STATUSES[2],
            staged.minor_units,
            flipped,
        ),
    ).fetchall()
    exact: list[str] = []
    near: list[str] = []
    seen: set[str] = set()
    candidates: list[tuple[str, int, int, bool]] = []
    for stx_id, proposed_date, minor, payee in rows:
        if stx_id in seen:
            continue
        seen.add(stx_id)
        delta = abs((date.fromisoformat(proposed_date) - target).days)
        in_window = delta <= window_days
        if in_window or minor == staged.minor_units:
            candidates.append((stx_id, delta, minor, _payees_match(staged.payee, payee)))
    exact_candidates = [c for c in candidates if c[2] == staged.minor_units and c[1] <= window_days]
    if exact_candidates:
        best_payee = max(c[3] for c in exact_candidates)
        ranked = [c for c in exact_candidates if c[3] == best_payee]
        nearest = min(c[1] for c in ranked)
        exact = [c[0] for c in ranked if c[1] == nearest]
    elif candidates:
        best_payee = max(c[3] for c in candidates)
        ranked = [c for c in candidates if c[3] == best_payee]
        nearest = min(c[1] for c in ranked)
        near = [c[0] for c in ranked if c[1] == nearest]
    return exact, near


def _payees_match(left: str, right: str) -> bool:
    left_canonical = canonical_payee(left)
    right_canonical = canonical_payee(right)
    if left_canonical == right_canonical:
        return True
    left_tokens = set(_PAYEE_TOKEN.findall(left_canonical))
    right_tokens = set(_PAYEE_TOKEN.findall(right_canonical))
    return bool(left_tokens & right_tokens)
