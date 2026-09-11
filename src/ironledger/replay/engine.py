"""Deterministic Audit Replay, Outbox Promotion, and Point-in-Time Engine."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ledger.topology import LedgerRegistry, validate_and_resolve_ledger_root
from ironledger.manifests import (
    GENESIS_MANIFEST_HASH,
    compute_directory_manifest_hash,
    compute_ledger_manifest_hash,
    render_compiled_ledger_manifest,
    render_price_directive_manifest,
)
from ironledger.replay.anchors import (
    compute_anchor_signature_digest,
    get_anchor_path,
    read_trust_anchor,
    sign_authority_payload,
    validate_anchor_ledger_id,
    verify_authority_signature,
    write_trust_anchor,
)
from ironledger.replay.models import (
    AuditTamperDetectedError,
    ManifestPromotionError,
    MissingAnchorCommitmentError,
    MutationPayload,
    ReconciliationFailedError,
    ReplayBoundaryError,
    ReplayError,
    ReplayResult,
    ReplayVerificationReport,
    SecurityError,
    TrustAnchor,
)
from ironledger.replay.schemas import validate_payload_schema
from ironledger.replay.snapshot import (
    GENESIS_PROJECTION_HASH,
    compute_projection_hash,
    dispatch_event_mutation,
)


def _get_journal_path(tenant_dir: Path) -> Path:
    return tenant_dir / ".promotion_journal.json"


def apply_mutation_and_append(
    conn: sqlite3.Connection,
    beancount_root: Path | str,
    ledger_id: str,
    operator_session: str,
    action: str,
    event_type: str,
    payload: dict[str, Any],
    payload_schema_version: int = 1,
    rules_applied: int = 0,
    rules_created: int = 0,
    authority_key: str | bytes = "ironledger-dev-key",
) -> tuple[dict[str, Any], MutationPayload]:
    """Execute in-memory mutation, generate outbox promotion, commit DB append-only event, and update external trust anchor."""
    validate_anchor_ledger_id(ledger_id)

    payload.setdefault("ledger_id", ledger_id)
    if event_type == "REVIEW_DECISION":
        payload.setdefault("prior_status", "pending")
        payload.setdefault("rule_id", None)
        payload.setdefault("reject_reason", None)
        payload.setdefault("assigned_account", None)
    elif event_type == "COMPILE_LEDGER":
        payload.setdefault("compiled_tx_ids", [])
        payload.setdefault("compiled_directives", [])
    elif event_type == "PRICE_DIRECTIVE":
        payload.setdefault("precision_scale", 4)
    elif event_type == "RULE_UPDATE":
        if "rule_id" in payload and isinstance(payload["rule_id"], int):
            payload["rule_id"] = str(payload["rule_id"])
        if "match_type" in payload and isinstance(payload["match_type"], str):
            payload["match_type"] = payload["match_type"].lower()
        payload.setdefault("importing_account", None)
        payload.setdefault("priority", 100)
        payload.setdefault("active", 1)

    validate_payload_schema(event_type, payload, payload_schema_version)

    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    tenant_dir = validate_and_resolve_ledger_root(beancount_root, ledger_id)
    current_dir = tenant_dir / "current"
    current_dir.mkdir(parents=True, exist_ok=True)

    registry = LedgerRegistry(conn, Path(beancount_root))
    with registry.acquire_compile_lock(ledger_id):
        sha256_before = compute_ledger_manifest_hash(beancount_root, ledger_id)
        projection_hash_before = compute_projection_hash(conn, ledger_id)

        staging_dir: Path | None = None
        if event_type in ("COMPILE_LEDGER", "PRICE_DIRECTIVE"):
            staging_dir = tenant_dir / f".staging_{uuid4().hex}"
            staging_dir.mkdir(parents=True, exist_ok=True)
            if current_dir.exists():
                for f in current_dir.glob("*.beancount"):
                    if f.is_file():
                        shutil.copy2(f, staging_dir / f.name)

            if event_type == "COMPILE_LEDGER":
                render_compiled_ledger_manifest(staging_dir, ledger_id, payload)
            elif event_type == "PRICE_DIRECTIVE":
                render_price_directive_manifest(staging_dir, ledger_id, payload)

            sha256_after = compute_directory_manifest_hash(staging_dir)
        else:
            sha256_after = sha256_before

        # Concurrency boundary: acquire transaction lock for monotonic sequence allocation
        in_tx = conn.in_transaction
        if not in_tx:
            conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute("SELECT seq, mutation_hash, ts_utc FROM mutation_events ORDER BY seq DESC LIMIT 1")
            last_event = cur.fetchone()
            if last_event is None:
                next_seq = 1
                prev_mutation_hash = "0" * 64
                last_ts = "1970-01-01T00:00:00Z"
            else:
                next_seq = last_event[0] + 1
                prev_mutation_hash = last_event[1]
                last_ts = last_event[2]

            now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if "created_at_utc" in payload and payload["created_at_utc"]:
                candidate_ts = payload["created_at_utc"]
            elif "decided_at_utc" in payload and payload["decided_at_utc"]:
                candidate_ts = payload["decided_at_utc"]
            else:
                candidate_ts = now_ts

            if not candidate_ts.endswith("Z"):
                candidate_ts += "Z"

            if candidate_ts <= last_ts:
                try:
                    clean_ts = last_ts.rstrip("Z")
                    if "." in clean_ts:
                        dt = datetime.datetime.fromisoformat(clean_ts).replace(tzinfo=datetime.timezone.utc)
                        dt = dt + datetime.timedelta(microseconds=1000)
                        ts_utc = dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    else:
                        dt = datetime.datetime.fromisoformat(clean_ts).replace(tzinfo=datetime.timezone.utc)
                        dt = dt + datetime.timedelta(seconds=1)
                        ts_utc = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    ts_utc = last_ts + "0"
            else:
                ts_utc = candidate_ts

            mutation_id = payload.get("mutation_id") or f"mut_{uuid4().hex[:12]}"

            dispatch_event_mutation(conn, ledger_id, event_type, payload)
            projection_hash_after = compute_projection_hash(conn, ledger_id)

            staged_count = 1 if event_type == "STAGE_TRANSACTION" else 0

            raw_mut = f"{next_seq}:{mutation_id}:{prev_mutation_hash}:{sha256_before}:{sha256_after}:{rules_applied}:{rules_created}:{payload_sha256}"
            mutation_hash = hashlib.sha256(raw_mut.encode("utf-8")).hexdigest()

            sig_digest = compute_anchor_signature_digest(
                seq=next_seq,
                mutation_id=mutation_id,
                ledger_id=ledger_id,
                ts_utc=ts_utc,
                mutation_hash=mutation_hash,
                prev_mutation_hash=prev_mutation_hash,
                manifest_hash=sha256_after,
                projection_hash=projection_hash_after,
            )
            authority_signature = sign_authority_payload(sig_digest, authority_key)

            journal_path = _get_journal_path(tenant_dir)
            journal_data = {
                "state": "PRE_COMMIT",
                "seq": next_seq,
                "mutation_id": mutation_id,
                "ledger_id": ledger_id,
                "ts_utc": ts_utc,
                "staging_dir": str(staging_dir) if staging_dir else None,
                "sha256_before": sha256_before,
                "sha256_after": sha256_after,
                "projection_hash_before": projection_hash_before,
                "projection_hash_after": projection_hash_after,
                "prev_mutation_hash": prev_mutation_hash,
                "mutation_hash": mutation_hash,
                "authority_signature": authority_signature,
                "payload_sha256": payload_sha256,
            }
            journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

            conn.execute(
                """
                INSERT INTO mutation_events (
                    seq, mutation_id, ledger_id, ts_utc, operator_session, action,
                    staged_count, rules_applied, rules_created, sha256_before, sha256_after,
                    prev_mutation_hash, mutation_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_seq, mutation_id, ledger_id, ts_utc, operator_session, action,
                    staged_count, rules_applied, rules_created, sha256_before, sha256_after,
                    prev_mutation_hash, mutation_hash,
                ),
            )
            conn.execute(
                """
                INSERT INTO mutation_payloads (
                    seq, mutation_id, ledger_id, payload_schema_version, event_type,
                    payload_json, payload_sha256, projection_hash_before, projection_hash_after,
                    authority_signature, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_seq, mutation_id, ledger_id, payload_schema_version, event_type,
                    payload_json, payload_sha256, projection_hash_before, projection_hash_after,
                    authority_signature, ts_utc,
                ),
            )
            if not in_tx:
                conn.commit()
        except Exception:
            if not in_tx:
                conn.rollback()
            raise

        journal_data["state"] = "COMMITTED_PRE_SWAP"
        journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

        if staging_dir is not None and staging_dir.exists():
            backup_dir = tenant_dir / f".backup_{uuid4().hex}"
            if current_dir.exists():
                os.replace(current_dir, backup_dir)
            os.replace(staging_dir, current_dir)
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

        anchor = TrustAnchor(
            anchor_version=1,
            ledger_id=ledger_id,
            seq=next_seq,
            mutation_id=mutation_id,
            mutation_hash=mutation_hash,
            prev_mutation_hash=prev_mutation_hash,
            manifest_hash=sha256_after,
            projection_hash=projection_hash_after,
            authority_signature=authority_signature,
            anchored_at_utc=ts_utc,
        )
        write_trust_anchor(beancount_root, anchor)

        journal_data["state"] = "SWAPPED"
        journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

        live_manifest = compute_ledger_manifest_hash(beancount_root, ledger_id)
        if live_manifest != sha256_after:
            raise ManifestPromotionError(
                f"Live manifest hash mismatch after promotion: expected {sha256_after}, got {live_manifest}"
            )
        live_proj = compute_projection_hash(conn, ledger_id)
        if live_proj != projection_hash_after:
            raise ManifestPromotionError(
                f"Live projection hash mismatch after promotion: expected {projection_hash_after}, got {live_proj}"
            )

        journal_path.unlink(missing_ok=True)

        event_record = {
            "seq": next_seq,
            "mutation_id": mutation_id,
            "ledger_id": ledger_id,
            "ts_utc": ts_utc,
            "operator_session": operator_session,
            "action": action,
            "staged_count": staged_count,
            "rules_applied": rules_applied,
            "rules_created": rules_created,
            "sha256_before": sha256_before,
            "sha256_after": sha256_after,
            "prev_mutation_hash": prev_mutation_hash,
            "mutation_hash": mutation_hash,
        }
        mutation_payload = MutationPayload(
            seq=next_seq,
            mutation_id=mutation_id,
            ledger_id=ledger_id,
            payload_schema_version=payload_schema_version,
            event_type=event_type,
            payload_json=payload_json,
            payload_sha256=payload_sha256,
            projection_hash_before=projection_hash_before,
            projection_hash_after=projection_hash_after,
            authority_signature=authority_signature,
            created_at=ts_utc,
        )
        return event_record, mutation_payload


def reconcile_manifest_on_startup(
    conn: sqlite3.Connection,
    beancount_root: Path | str,
    authority_key: str | bytes = "ironledger-dev-key",
) -> None:
    """Startup reconciliation: verify journals, complete pending directory swaps, and validate trust anchors and live manifests."""
    cur = conn.execute("SELECT ledger_id FROM ledgers WHERE is_active = 1")
    active_ledgers = [row[0] for row in cur.fetchall()]

    for ledger_id in active_ledgers:
        validate_anchor_ledger_id(ledger_id)
        tenant_dir = validate_and_resolve_ledger_root(beancount_root, ledger_id)
        current_dir = tenant_dir / "current"
        current_dir.mkdir(parents=True, exist_ok=True)
        journal_path = _get_journal_path(tenant_dir)

        if journal_path.exists():
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
            except Exception as e:
                raise ReconciliationFailedError(f"Corrupt promotion journal for ledger '{ledger_id}': {e}") from e

            state = journal.get("state")
            seq = journal.get("seq")
            staging_str = journal.get("staging_dir")
            staging_path = Path(staging_str) if staging_str else None

            cur_seq = conn.execute("SELECT seq FROM mutation_events WHERE seq = ?", (seq,)).fetchone()
            in_db = cur_seq is not None

            if state == "PRE_COMMIT":
                if not in_db:
                    if staging_path and staging_path.exists():
                        shutil.rmtree(staging_path, ignore_errors=True)
                    journal_path.unlink(missing_ok=True)
                else:
                    state = "COMMITTED_PRE_SWAP"

            if state == "COMMITTED_PRE_SWAP":
                if staging_path and staging_path.exists():
                    staged_manifest = compute_directory_manifest_hash(staging_path)
                    if staged_manifest != journal["sha256_after"]:
                        raise ReconciliationFailedError(
                            f"Staged recovery manifest hash mismatch: expected {journal['sha256_after']}, got {staged_manifest}"
                        )
                    backup_dir = tenant_dir / f".backup_{uuid4().hex}"
                    if current_dir.exists():
                        os.replace(current_dir, backup_dir)
                    os.replace(staging_path, current_dir)
                    if backup_dir.exists():
                        shutil.rmtree(backup_dir, ignore_errors=True)

                sig_digest = compute_anchor_signature_digest(
                    seq=journal["seq"],
                    mutation_id=journal["mutation_id"],
                    ledger_id=ledger_id,
                    ts_utc=journal["ts_utc"],
                    mutation_hash=journal["mutation_hash"],
                    prev_mutation_hash=journal["prev_mutation_hash"],
                    manifest_hash=journal["sha256_after"],
                    projection_hash=journal["projection_hash_after"],
                )
                sig = sign_authority_payload(sig_digest, authority_key)

                anchor = TrustAnchor(
                    anchor_version=1,
                    ledger_id=ledger_id,
                    seq=journal["seq"],
                    mutation_id=journal["mutation_id"],
                    mutation_hash=journal["mutation_hash"],
                    prev_mutation_hash=journal["prev_mutation_hash"],
                    manifest_hash=journal["sha256_after"],
                    projection_hash=journal["projection_hash_after"],
                    authority_signature=sig,
                    anchored_at_utc=journal["ts_utc"],
                )
                write_trust_anchor(beancount_root, anchor)
                state = "SWAPPED"

            if state == "SWAPPED":
                journal_path.unlink(missing_ok=True)

        cur_tip = conn.execute(
            """
            SELECT e.seq, e.mutation_id, e.mutation_hash, e.prev_mutation_hash, e.sha256_after, e.ts_utc,
                   p.projection_hash_after, p.authority_signature
            FROM mutation_events e
            JOIN mutation_payloads p ON e.seq = p.seq
            WHERE e.ledger_id = ?
            ORDER BY e.seq DESC LIMIT 1
            """,
            (ledger_id,),
        )
        tip_row = cur_tip.fetchone()
        if tip_row is not None:
            tip_seq, tip_mut_id, tip_mut_hash, tip_prev_hash, tip_manifest, tip_ts, tip_proj, tip_auth_sig = tip_row
            anchor_path = get_anchor_path(beancount_root, ledger_id)
            if not anchor_path.exists():
                raise MissingAnchorCommitmentError(
                    f"Missing external trust anchor file for ledger '{ledger_id}' with committed events"
                )

            anchor = read_trust_anchor(beancount_root, ledger_id)
            if (
                anchor.seq != tip_seq
                or anchor.mutation_id != tip_mut_id
                or anchor.mutation_hash != tip_mut_hash
                or anchor.prev_mutation_hash != tip_prev_hash
                or anchor.manifest_hash != tip_manifest
                or anchor.projection_hash != tip_proj
                or anchor.anchored_at_utc != tip_ts
                or (tip_auth_sig and anchor.authority_signature != tip_auth_sig)
            ):
                raise ReconciliationFailedError(
                    f"Trust anchor tip does not match DB tip for ledger '{ledger_id}'"
                )
            sig_digest = compute_anchor_signature_digest(
                seq=anchor.seq,
                mutation_id=anchor.mutation_id,
                ledger_id=anchor.ledger_id,
                ts_utc=anchor.anchored_at_utc,
                mutation_hash=anchor.mutation_hash,
                prev_mutation_hash=anchor.prev_mutation_hash,
                manifest_hash=anchor.manifest_hash,
                projection_hash=anchor.projection_hash,
            )
            if not verify_authority_signature(anchor.authority_signature, sig_digest, authority_key):
                raise AuditTamperDetectedError(f"Trust anchor signature verification failed for ledger '{ledger_id}'")

            live_manifest = compute_ledger_manifest_hash(beancount_root, ledger_id)
            if live_manifest != tip_manifest:
                raise AuditTamperDetectedError(
                    f"Live manifest hash mismatch for ledger '{ledger_id}': live={live_manifest}, recorded={tip_manifest}"
                )
        else:
            live_manifest = compute_ledger_manifest_hash(beancount_root, ledger_id)
            if live_manifest != GENESIS_MANIFEST_HASH:
                raise AuditTamperDetectedError(
                    f"Untracked files detected in empty ledger '{ledger_id}': live={live_manifest}"
                )


def replay_audit_stream(
    live_conn: sqlite3.Connection,
    beancount_root: Path | str,
    target_ledger_id: str,
    target_seq: int | None = None,
    target_timestamp: str | None = None,
    authority_key: str | bytes = "ironledger-dev-key",
) -> ReplayResult:
    """Deterministic Point-in-Time audit replay over global mutation stream."""
    validate_anchor_ledger_id(target_ledger_id)

    total_events_count = live_conn.execute("SELECT COUNT(*) FROM mutation_events").fetchone()[0]
    if total_events_count == 0:
        live_manifest = compute_ledger_manifest_hash(beancount_root, target_ledger_id)
        if live_manifest != GENESIS_MANIFEST_HASH:
            raise AuditTamperDetectedError(
                f"Untracked files detected in empty ledger: live={live_manifest}, expected={GENESIS_MANIFEST_HASH}"
            )

        replay_conn = connect(":memory:")
        migrations.migrate(replay_conn)
        temp_dir = Path(tempfile.mkdtemp(prefix="ironledger_replay_"))
        report = ReplayVerificationReport(
            total_events_verified=0,
            target_ledger_events_replayed=0,
            interleaved_events_skipped=0,
            final_sequence=0,
            final_projection_hash=GENESIS_PROJECTION_HASH,
            final_manifest_hash=GENESIS_MANIFEST_HASH,
            verified_anchor=None,
            replay_success=True,
        )
        return ReplayResult(report=report, projection_conn=replay_conn, manifest_dir=temp_dir)

    max_seq_db = live_conn.execute("SELECT MAX(seq) FROM mutation_events").fetchone()[0]

    if target_seq is not None:
        if target_seq < 1 or target_seq > max_seq_db:
            raise ReplayBoundaryError(f"Target sequence {target_seq} out of bounds [1, {max_seq_db}]")
        effective_target_seq = target_seq
    elif target_timestamp is not None:
        ts_query = target_timestamp if target_timestamp.endswith("Z") else target_timestamp + "Z"
        row = live_conn.execute(
            "SELECT MAX(seq) FROM mutation_events WHERE ts_utc <= ?", (ts_query,)
        ).fetchone()
        if row is None or row[0] is None:
            raise ReplayBoundaryError(f"No mutation events found before target timestamp '{target_timestamp}'")
        effective_target_seq = row[0]
    else:
        effective_target_seq = max_seq_db

    # Check for legacy unreplayable events
    payloads_count = live_conn.execute(
        "SELECT COUNT(*) FROM mutation_payloads WHERE seq <= ?", (effective_target_seq,)
    ).fetchone()[0]
    if payloads_count != effective_target_seq:
        raise AuditTamperDetectedError(
            f"Audit stream contains unreplayable legacy events without payloads ({payloads_count} payloads for {effective_target_seq} events)"
        )

    target_tip_row = live_conn.execute(
        """
        SELECT e.seq, e.mutation_id, e.mutation_hash, e.prev_mutation_hash, e.sha256_after, e.ts_utc,
               p.projection_hash_after
        FROM mutation_events e
        JOIN mutation_payloads p ON e.seq = p.seq
        WHERE e.ledger_id = ?
        ORDER BY e.seq DESC LIMIT 1
        """,
        (target_ledger_id,),
    ).fetchone()

    verified_anchor: TrustAnchor | None = None
    if target_tip_row is not None and effective_target_seq >= target_tip_row[0]:
        anchor = read_trust_anchor(beancount_root, target_ledger_id)
        sig_digest = compute_anchor_signature_digest(
            seq=anchor.seq,
            mutation_id=anchor.mutation_id,
            ledger_id=anchor.ledger_id,
            ts_utc=anchor.anchored_at_utc,
            mutation_hash=anchor.mutation_hash,
            prev_mutation_hash=anchor.prev_mutation_hash,
            manifest_hash=anchor.manifest_hash,
            projection_hash=anchor.projection_hash,
        )
        if not verify_authority_signature(anchor.authority_signature, sig_digest, authority_key):
            raise AuditTamperDetectedError(f"External trust anchor signature invalid for '{target_ledger_id}'")
        if (
            anchor.seq != target_tip_row[0]
            or anchor.mutation_id != target_tip_row[1]
            or anchor.mutation_hash != target_tip_row[2]
            or anchor.prev_mutation_hash != target_tip_row[3]
            or anchor.manifest_hash != target_tip_row[4]
            or anchor.anchored_at_utc != target_tip_row[5]
            or anchor.projection_hash != target_tip_row[6]
        ):
            raise AuditTamperDetectedError(
                f"External trust anchor does not match DB tip for ledger '{target_ledger_id}'"
            )
        verified_anchor = anchor

    cur = live_conn.execute(
        """
        SELECT
            e.seq, e.mutation_id, e.ledger_id, e.ts_utc, e.operator_session, e.action,
            e.staged_count, e.rules_applied, e.rules_created, e.sha256_before, e.sha256_after,
            e.prev_mutation_hash, e.mutation_hash,
            p.payload_schema_version, p.event_type, p.payload_json, p.payload_sha256,
            p.projection_hash_before, p.projection_hash_after, p.authority_signature
        FROM mutation_events e
        JOIN mutation_payloads p ON e.seq = p.seq
        WHERE e.seq <= ?
        ORDER BY e.seq ASC
        """,
        (effective_target_seq,),
    )
    rows = cur.fetchall()

    replay_conn = connect(":memory:")
    migrations.migrate(replay_conn)
    replay_manifest_dir = Path(tempfile.mkdtemp(prefix="ironledger_replay_"))

    cur_ledgers = live_conn.execute(
        "SELECT ledger_id, name, root_account, base_currency, storage_root, is_active, created_at FROM ledgers"
    )
    for row in cur_ledgers.fetchall():
        replay_conn.execute(
            """
            INSERT OR REPLACE INTO ledgers (
                ledger_id, name, root_account, base_currency, storage_root, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
    replay_conn.commit()

    expected_seq = 1
    expected_prev_hash = "0" * 64
    last_ts = "1970-01-01T00:00:00Z"

    total_events_verified = 0
    target_ledger_events_replayed = 0
    interleaved_events_skipped = 0

    for r in rows:
        seq = r[0]
        mut_id = r[1]
        row_ledger_id = r[2]
        ts_utc = r[3]
        operator_session = r[4]
        action = r[5]
        staged_count = r[6]
        rules_applied = r[7]
        rules_created = r[8]
        sha256_before = r[9]
        sha256_after = r[10]
        prev_mutation_hash = r[11]
        mutation_hash = r[12]
        payload_schema_version = r[13]
        event_type = r[14]
        payload_json = r[15]
        payload_sha256 = r[16]
        projection_hash_before = r[17]
        projection_hash_after = r[18]
        row_authority_sig = r[19]

        if seq != expected_seq:
            raise AuditTamperDetectedError(f"Sequence break detected at seq {seq}, expected {expected_seq}")
        if prev_mutation_hash != expected_prev_hash:
            raise AuditTamperDetectedError(
                f"Broken Merkle hash chain at seq {seq}: prev_hash={prev_mutation_hash}, expected={expected_prev_hash}"
            )
        if ts_utc < last_ts:
            raise AuditTamperDetectedError(f"Non-monotonic timestamp detected at seq {seq}: {ts_utc} < {last_ts}")

        computed_payload_sha = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if computed_payload_sha != payload_sha256:
            raise AuditTamperDetectedError(f"Payload SHA-256 mismatch at seq {seq}")

        raw_mut = f"{seq}:{mut_id}:{prev_mutation_hash}:{sha256_before}:{sha256_after}:{rules_applied}:{rules_created}:{payload_sha256}"
        computed_mut_hash = hashlib.sha256(raw_mut.encode("utf-8")).hexdigest()
        if computed_mut_hash != mutation_hash:
            raise AuditTamperDetectedError(
                f"Mutation hash mismatch at seq {seq}: computed={computed_mut_hash}, db={mutation_hash}"
            )

        sig_digest = compute_anchor_signature_digest(
            seq=seq,
            mutation_id=mut_id,
            ledger_id=row_ledger_id,
            ts_utc=ts_utc,
            mutation_hash=mutation_hash,
            prev_mutation_hash=prev_mutation_hash,
            manifest_hash=sha256_after,
            projection_hash=projection_hash_after,
        )
        if not verify_authority_signature(row_authority_sig, sig_digest, authority_key):
            raise AuditTamperDetectedError(f"Authority signature invalid at seq {seq}")

        total_events_verified += 1
        expected_seq += 1
        expected_prev_hash = mutation_hash
        last_ts = ts_utc

        if row_ledger_id != target_ledger_id:
            interleaved_events_skipped += 1
            continue

        target_ledger_events_replayed += 1

        current_replay_proj = compute_projection_hash(replay_conn, target_ledger_id)
        if current_replay_proj != projection_hash_before:
            raise AuditTamperDetectedError(
                f"Replay projection before-state mismatch at seq {seq}: expected {projection_hash_before}, got {current_replay_proj}"
            )
        current_replay_manifest = compute_directory_manifest_hash(replay_manifest_dir)
        if current_replay_manifest != sha256_before:
            raise AuditTamperDetectedError(
                f"Replay manifest before-state mismatch at seq {seq}: expected {sha256_before}, got {current_replay_manifest}"
            )

        payload = json.loads(payload_json)
        dispatch_event_mutation(replay_conn, target_ledger_id, event_type, payload)

        if event_type == "COMPILE_LEDGER":
            render_compiled_ledger_manifest(replay_manifest_dir, target_ledger_id, payload)
        elif event_type == "PRICE_DIRECTIVE":
            render_price_directive_manifest(replay_manifest_dir, target_ledger_id, payload)

        after_replay_proj = compute_projection_hash(replay_conn, target_ledger_id)
        if after_replay_proj != projection_hash_after:
            raise AuditTamperDetectedError(
                f"Replay projection after-state mismatch at seq {seq}: expected {projection_hash_after}, got {after_replay_proj}"
            )
        after_replay_manifest = compute_directory_manifest_hash(replay_manifest_dir)
        if after_replay_manifest != sha256_after:
            raise AuditTamperDetectedError(
                f"Replay manifest after-state mismatch at seq {seq}: expected {sha256_after}, got {after_replay_manifest}"
            )

    final_proj = compute_projection_hash(replay_conn, target_ledger_id)
    final_manifest = compute_directory_manifest_hash(replay_manifest_dir)

    report = ReplayVerificationReport(
        total_events_verified=total_events_verified,
        target_ledger_events_replayed=target_ledger_events_replayed,
        interleaved_events_skipped=interleaved_events_skipped,
        final_sequence=effective_target_seq,
        final_projection_hash=final_proj,
        final_manifest_hash=final_manifest,
        verified_anchor=verified_anchor,
        replay_success=True,
    )
    return ReplayResult(report=report, projection_conn=replay_conn, manifest_dir=replay_manifest_dir)
