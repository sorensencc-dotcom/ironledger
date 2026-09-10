"""End-to-End Governance Acceptance Suite for IronLedger Phase 6.

Verifies the full integrated lifecycle across all Phase 6 governance engines:
1. Schema migration pre-flight and execution (migrate_governed, verify_schema_checksums, FK checks).
2. Stateless step-up HMAC token generation and validation under active Safe Mode.
3. Authorized ledger compilation with BEGIN IMMEDIATE and mutation event generation (append_mutation_event).
4. Unbroken cryptographic mutation chain verification (verify_mutation_chain).
5. Live projection freshness evaluation and SLA status checks (check_projection_db_freshness).
6. Rule drift auditing and HCT calculation (audit_all_rules_drift).
7. Rejection and audit event recording for unauthorized/tampered requests.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ironledger.audit import append_audit_event
from ironledger.db.connection import connect
from ironledger.governance import (
    ChecksumMismatch,
    ForeignKeyViolationError,
    FreshnessTier,
    GENESIS_MUTATION_PREV_HASH,
    MigrationError,
    MutationEvent,
    MutationVerificationError,
    MutationVerificationResult,
    ProjectionFreshnessResult,
    RuleDriftMetrics,
    RuleHealthTier,
    SafeModeAuthorizationError,
    append_mutation_event,
    applied_migrations,
    audit_all_rules_drift,
    calculate_hct,
    check_projection_db_freshness,
    compute_canonical_ledger_manifest_hash,
    create_step_up_token,
    current_version,
    discover_migrations,
    evaluate_projection_freshness,
    evaluate_rule_drift,
    get_safe_mode_secret,
    load_mutation_events,
    migrate_governed,
    require_governed_authorization,
    safe_mode_enabled,
    verify_mutation_chain,
    verify_schema_checksums,
    verify_step_up_token,
)


def _setup_ledger_dir(base_dir: Path) -> Path:
    """Create a minimal valid Beancount ledger directory."""
    ledger_dir = base_dir / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    main_bc = ledger_dir / "main.beancount"
    main_bc.write_text(
        '2026-01-01 open Assets:Bank:Checking USD\n'
        '2026-01-01 open Expenses:Groceries USD\n'
        '2026-01-01 open Equity:Opening-Balances USD\n'
        '2026-01-02 * "Opening balance"\n'
        '  Assets:Bank:Checking  1000.00 USD\n'
        '  Equity:Opening-Balances\n',
        encoding="utf-8",
    )
    return ledger_dir


def _setup_safe_mode_config(config_dir: Path, enabled: bool = True, secret: str = "e2e-secret-key-phase6") -> Path:
    """Create a safe-mode configuration directory."""
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = config_dir / "safe-mode.json"
    cfg_file.write_text(
        json.dumps({"enabled": enabled, "safe_mode_secret": secret}),
        encoding="utf-8",
    )
    return config_dir


# ============================================================================
# 1. Schema Migration Pre-flight and Execution
# ============================================================================


def test_e2e_schema_migration_preflight_and_fk_enforcement(tmp_path: Path):
    """Verify forward-only migration runner with pre-flight checksum verification and FK check."""
    db_path = tmp_path / "ironledger_e2e.db"
    conn = connect(db_path)

    # 1. Discover packaged migrations
    migrations = discover_migrations()
    assert len(migrations) >= 6
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))

    # 2. Run governed migrations
    version = migrate_governed(conn)
    assert version >= 6
    assert current_version(conn) == version

    # 3. Verify recorded migrations and checksum integrity
    applied = applied_migrations(conn)
    assert len(applied) == len(migrations)
    for v, name, csum in applied:
        assert len(csum) == 64
    assert verify_schema_checksums(conn) is True

    # 4. Idempotency: Re-running does not re-apply or fail
    version2 = migrate_governed(conn)
    assert version2 == version

    # 5. Pre-flight verification catches disk tampering on a custom schema set
    mig_dir = tmp_path / "custom_schema"
    mig_dir.mkdir()
    f1 = mig_dir / "0001_initial.sql"
    f1.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY) STRICT;\n", encoding="utf-8")
    
    custom_conn = connect(tmp_path / "custom.db")
    assert migrate_governed(custom_conn, directory=mig_dir) == 1
    assert verify_schema_checksums(custom_conn, directory=mig_dir) is True

    # Tamper with 0001_initial.sql on disk
    f1.write_text("CREATE TABLE alpha (id INTEGER PRIMARY KEY, extra TEXT) STRICT;\n", encoding="utf-8")
    with pytest.raises(ChecksumMismatch, match="changed on disk after being applied"):
        verify_schema_checksums(custom_conn, directory=mig_dir)

    # Pre-flight blocks pending migration 0002 when earlier migration was tampered
    f2 = mig_dir / "0002_next.sql"
    f2.write_text("CREATE TABLE beta (id INTEGER PRIMARY KEY) STRICT;\n", encoding="utf-8")
    with pytest.raises(ChecksumMismatch, match="changed on disk after being applied"):
        migrate_governed(custom_conn, directory=mig_dir)

    # 6. Foreign key enforcement fails closed on invalid references
    fk_mig_dir = tmp_path / "fk_schema"
    fk_mig_dir.mkdir()
    (fk_mig_dir / "0001_parent.sql").write_text(
        "CREATE TABLE p (id INTEGER PRIMARY KEY) STRICT;\n"
        "CREATE TABLE c (id INTEGER PRIMARY KEY, p_id INTEGER NOT NULL REFERENCES p(id)) STRICT;\n",
        encoding="utf-8",
    )
    (fk_mig_dir / "0002_bad_fk.sql").write_text(
        "PRAGMA defer_foreign_keys = ON;\n"
        "INSERT INTO c (id, p_id) VALUES (1, 9999);\n",
        encoding="utf-8",
    )
    fk_conn = connect(tmp_path / "fk.db")
    with pytest.raises(ForeignKeyViolationError, match="foreign key check failed"):
        migrate_governed(fk_conn, directory=fk_mig_dir)
    assert current_version(fk_conn) == 1

    conn.close()
    custom_conn.close()
    fk_conn.close()


# ============================================================================
# 2. Stateless Step-Up HMAC Tokens & Safe Mode Authorization Gate
# ============================================================================


def test_e2e_safe_mode_authorization_and_rejections(tmp_path: Path):
    """Verify stateless HMAC tokens, fail-closed safe mode, and rejection audit logging."""
    conn = connect(":memory:")
    migrate_governed(conn)
    config_dir = tmp_path / "config"
    secret = "e2e-secret-key-phase6"
    _setup_safe_mode_config(config_dir, enabled=True, secret=secret)

    target_hash = "f" * 64
    actor = "lead_auditor"

    assert safe_mode_enabled(config_dir) is True
    assert get_safe_mode_secret(config_dir) == secret

    # 1. Unauthenticated attempt is denied and recorded in audit_events
    with pytest.raises(SafeModeAuthorizationError, match="cryptographic step-up token required"):
        require_governed_authorization(
            conn,
            token=None,
            phrase=None,
            scope="compile",
            target_digest=target_hash,
            config_dir=config_dir,
            actor=actor,
        )

    last_audit = conn.execute(
        "SELECT actor, action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert last_audit[0] == actor
    assert "compile" in last_audit[1]
    assert last_audit[2] == target_hash
    assert last_audit[3] == "denied"

    # 2. Tampered token signature is denied and recorded
    valid_token = create_step_up_token(
        secret,
        actor=actor,
        scope="compile",
        target_digest=target_hash,
        ttl_seconds=300,
    )
    payload_b64, sig = valid_token.split(".")
    tampered_token = f"{payload_b64}.{'0' * len(sig)}"
    with pytest.raises(SafeModeAuthorizationError, match="invalid step-up token signature"):
        require_governed_authorization(
            conn,
            token=tampered_token,
            scope="compile",
            target_digest=target_hash,
            config_dir=config_dir,
            actor=actor,
        )

    last_audit = conn.execute(
        "SELECT actor, action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert last_audit[3] == "denied"

    # 3. Expired token is denied
    now_epoch = 1750000000
    expired_token = create_step_up_token(
        secret,
        actor=actor,
        scope="compile",
        target_digest=target_hash,
        ttl_seconds=60,
        now_epoch=now_epoch - 120,
    )
    with pytest.raises(SafeModeAuthorizationError, match="expired"):
        verify_step_up_token(
            expired_token,
            secret,
            expected_scope="compile",
            expected_target_digest=target_hash,
            now_epoch=now_epoch,
        )

    # 4. Scope mismatch is denied
    with pytest.raises(SafeModeAuthorizationError, match="token scope mismatch"):
        verify_step_up_token(
            valid_token,
            secret,
            expected_scope="project",
            expected_target_digest=target_hash,
        )

    # 5. Target digest mismatch is denied
    with pytest.raises(SafeModeAuthorizationError, match="token target_digest mismatch"):
        verify_step_up_token(
            valid_token,
            secret,
            expected_scope="compile",
            expected_target_digest="0" * 64,
        )

    # 6. Valid token is accepted and recorded as ok
    auth_result = require_governed_authorization(
        conn,
        token=valid_token,
        scope="compile",
        target_digest=target_hash,
        config_dir=config_dir,
        actor=actor,
    )
    assert auth_result["authorized"] is True
    assert auth_result["result"] == "authorized"
    assert auth_result["mechanism"] == "token"

    last_audit = conn.execute(
        "SELECT actor, action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert last_audit[0] == actor
    assert "authorize compile (step-up)" in last_audit[1]
    assert last_audit[3] == "ok"

    conn.close()


# ============================================================================
# 3. Mutation Ledger Engine & Unbroken Cryptographic Chain
# ============================================================================


def test_e2e_mutation_chain_lifecycle_and_tamper_detection(tmp_path: Path):
    """Verify serialized mutation event recording, monotonic hash chaining, and tamper detection."""
    conn = connect(":memory:")
    migrate_governed(conn)
    ledger_dir = _setup_ledger_dir(tmp_path)

    # Compute canonical manifest hashes before and after mutation
    h0 = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert len(h0) == 64

    # Append first mutation
    h1 = "1" * 64
    ev1 = append_mutation_event(
        conn,
        operator_session="sess_e2e_1",
        action="compile",
        staged_count=3,
        rules_applied=2,
        rules_created=1,
        sha256_before=h0,
        sha256_after=h1,
        ts_utc="2026-09-09T10:00:00Z",
    )
    assert ev1.seq == 1
    assert ev1.prev_mutation_hash == GENESIS_MUTATION_PREV_HASH
    assert len(ev1.mutation_hash) == 64

    # Append second mutation chained to ev1
    h2 = "2" * 64
    ev2 = append_mutation_event(
        conn,
        operator_session="sess_e2e_2",
        action="compile",
        staged_count=5,
        rules_applied=4,
        rules_created=0,
        sha256_before=h1,
        sha256_after=h2,
        ts_utc="2026-09-09T11:00:00Z",
    )
    assert ev2.seq == 2
    assert ev2.prev_mutation_hash == ev1.mutation_hash
    assert len(ev2.mutation_hash) == 64

    # Append third mutation chained to ev2
    h3 = "3" * 64
    ev3 = append_mutation_event(
        conn,
        operator_session="sess_e2e_3",
        action="project",
        staged_count=0,
        rules_applied=0,
        rules_created=0,
        sha256_before=h2,
        sha256_after=h3,
        ts_utc="2026-09-09T12:00:00Z",
    )
    assert ev3.seq == 3
    assert ev3.prev_mutation_hash == ev2.mutation_hash

    # Verify unbroken mutation chain
    verification = verify_mutation_chain(conn)
    assert verification.is_valid is True
    assert verification.mutation_count == 3
    assert verification.head_hash == ev3.mutation_hash

    # Verify triggers enforce append-only immutability
    with pytest.raises(sqlite3.IntegrityError, match="forbidden"):
        conn.execute("UPDATE mutation_events SET staged_count = 99 WHERE seq = 1")

    with pytest.raises(sqlite3.IntegrityError, match="forbidden"):
        conn.execute("DELETE FROM mutation_events WHERE seq = 3")

    # Tamper detection: bypass trigger to simulate disk or database corruption
    conn.execute("DROP TRIGGER IF EXISTS mutation_events_no_update")
    conn.execute("UPDATE mutation_events SET staged_count = 99 WHERE seq = 2")

    with pytest.raises(MutationVerificationError, match="hash mismatch"):
        verify_mutation_chain(conn)

    conn.close()


# ============================================================================
# 4. Live Projection Freshness & SLA Status
# ============================================================================


def test_e2e_projection_freshness_and_sla_checks(tmp_path: Path):
    """Verify projection freshness evaluation, unidirectional latency clamp, and hash divergence."""
    ledger_dir = _setup_ledger_dir(tmp_path)
    ledger_hash = compute_canonical_ledger_manifest_hash(ledger_dir)

    proj_db = tmp_path / "projection.sqlite"
    built_at = "2026-09-09T12:00:00Z"

    with sqlite3.connect(str(proj_db)) as pconn:
        pconn.execute(
            """
            CREATE TABLE projection_meta (
                singleton INTEGER PRIMARY KEY,
                built_at_utc TEXT NOT NULL,
                ledger_output_hash TEXT NOT NULL
            ) STRICT
            """
        )
        pconn.execute(
            "INSERT INTO projection_meta (singleton, built_at_utc, ledger_output_hash) VALUES (1, ?, ?)",
            (built_at, ledger_hash),
        )
        pconn.commit()

    # 1. Fresh SLA: evaluated 2 seconds later
    res_fresh = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T12:00:02Z",
    )
    assert res_fresh.status == FreshnessTier.FRESH
    assert res_fresh.latency_seconds == 2.0
    assert res_fresh.source_hash_match is True
    assert res_fresh.ledger_source_sha256 == ledger_hash
    assert res_fresh.projection_source_sha256 == ledger_hash

    # 2. Stale SLA: evaluated 15 seconds later (5s <= latency <= 30s)
    res_stale = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T12:00:15Z",
    )
    assert res_stale.status == FreshnessTier.STALE
    assert res_stale.latency_seconds == 15.0
    assert res_stale.source_hash_match is True

    # 3. Critical SLA: evaluated 45 seconds later (>30s)
    res_critical = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T12:00:45Z",
    )
    assert res_critical.status == FreshnessTier.CRITICAL
    assert res_critical.latency_seconds == 45.0
    assert res_critical.source_hash_match is True

    # 4. Clock rollback tolerance: future built_at clamped to 0.0s latency
    res_clock = evaluate_projection_freshness(
        ledger_source_sha256=ledger_hash,
        projection_source_sha256=ledger_hash,
        built_at_utc="2026-09-09T12:05:00Z",
        now_utc="2026-09-09T12:00:00Z",
    )
    assert res_clock.latency_seconds == 0.0
    assert res_clock.status == FreshnessTier.FRESH

    # 5. Live hash divergence: ledger modified on disk independently forces CRITICAL
    main_bc = ledger_dir / "main.beancount"
    main_bc.write_text(
        main_bc.read_text(encoding="utf-8")
        + '2026-01-03 * "Coffee"\n  Expenses:Groceries 5.50 USD\n  Assets:Bank:Checking\n',
        encoding="utf-8",
    )
    new_ledger_hash = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert new_ledger_hash != ledger_hash

    res_desync = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T12:00:01Z",
    )
    assert res_desync.status == FreshnessTier.CRITICAL
    assert res_desync.source_hash_match is False
    assert res_desync.latency_seconds == 1.0


# ============================================================================
# 5. Rule Drift Auditing & Hit Confidence Trend (HCT)
# ============================================================================


def test_e2e_rule_drift_and_hct_auditing():
    """Verify HCT calculation, time decay, provisional thresholds, and health tier classification."""
    # 1. Direct mathematical formula verification
    assert calculate_hct(hits=100, overrides=0, days_since_last_hit=0.0) == 1.0
    assert pytest.approx(calculate_hct(hits=100, overrides=5, days_since_last_hit=0.0), 0.001) == 0.925
    assert pytest.approx(calculate_hct(hits=100, overrides=0, days_since_last_hit=20.0), 0.001) == 0.90
    assert calculate_hct(hits=100, overrides=90, days_since_last_hit=0.0) == 0.0

    # 2. Database audit verification across all tiers
    conn = connect(":memory:")
    migrate_governed(conn)

    # Insert review rules
    rules_data = [
        # Evaluating: < 5 hits -> evaluating (provisional=True)
        ("rule_eval", "eval", "Expenses:Eval", 3, 0, "2026-09-09T11:50:00Z"),
        # Healthy: 100 hits, 2 overrides -> HCT = 0.97, O_R = 0.02 -> healthy
        ("rule_healthy", "coffee", "Expenses:Coffee", 100, 2, "2026-09-09T11:50:00Z"),
        # Warning: 100 hits, 8 overrides -> HCT = 0.88, O_R = 0.08 -> warning
        ("rule_warning", "uber", "Expenses:Transport", 100, 8, "2026-09-09T11:50:00Z"),
        # Critical: 100 hits, 20 overrides -> O_R = 0.20 >= 0.15 -> critical
        ("rule_critical", "hardware", "Expenses:Gadgets", 100, 20, "2026-09-09T11:50:00Z"),
        # Time decay warning: 100 hits, 0 overrides, last hit 80 days ago -> HCT = 1.0 - 0.4 = 0.60 -> warning
        ("rule_decayed", "stale_payee", "Expenses:Old", 100, 0, "2026-06-21T12:00:00Z"),
    ]

    for rid, pat, target_acc, hits, overrides, last_hit in rules_data:
        conn.execute(
            "INSERT INTO categorization_rules "
            "(rule_id, match_type, pattern, target_account, priority, active, created_at_utc) "
            "VALUES (?, 'prefix', ?, ?, 100, 1, '2026-01-01T00:00:00Z')",
            (rid, pat, target_acc),
        )
        # Record matching audit events
        for i in range(hits - overrides):
            append_audit_event(
                conn,
                actor="system",
                action=f"review auto-match ({target_acc}; rule {rid})",
                target=f"stx_{rid}_{i}",
                result="ok",
                ts_utc=last_hit,
            )
        for i in range(overrides):
            append_audit_event(
                conn,
                actor="operator",
                action=f"review override ({target_acc}; rule {rid})",
                target=f"stx_ovr_{rid}_{i}",
                result="ok",
                ts_utc=last_hit,
            )
    conn.commit()

    drift_results = audit_all_rules_drift(conn, now_utc="2026-09-09T12:00:00Z")
    assert len(drift_results) == 5
    result_map = {r.rule_id: r for r in drift_results}

    assert result_map["rule_eval"].tier == RuleHealthTier.EVALUATING
    assert result_map["rule_eval"].provisional is True

    assert result_map["rule_healthy"].tier == RuleHealthTier.HEALTHY
    assert result_map["rule_healthy"].provisional is False
    assert result_map["rule_healthy"].override_rate == 0.02

    assert result_map["rule_warning"].tier == RuleHealthTier.WARNING
    assert result_map["rule_warning"].override_rate == 0.08

    assert result_map["rule_critical"].tier == RuleHealthTier.CRITICAL
    assert result_map["rule_critical"].override_rate == 0.20

    assert result_map["rule_decayed"].tier == RuleHealthTier.WARNING
    assert pytest.approx(result_map["rule_decayed"].hct, 0.01) == 0.60

    conn.close()


# ============================================================================
# 6. Full Integrated Governance Lifecycle Pipeline
# ============================================================================


def test_e2e_governance_full_lifecycle_integrated_pipeline(tmp_path: Path):
    """Full integrated lifecycle uniting all Phase 6 governance engines into a single pipeline.

    Flow:
    1. Schema migration execution with pre-flight checksum & FK validation.
    2. Active Safe Mode configuration and fail-closed rejection of unauthorized actions.
    3. Stateless step-up HMAC token creation, validation, and audit recording.
    4. Plaintext ledger mutation, manifest digest computation, and BEGIN IMMEDIATE mutation logging.
    5. Second mutation chained to the first, proving monotonic seq and previous hash linkage.
    6. Unbroken cryptographic chain verification.
    7. Projection database freshness and SLA monitoring against the live ledger.
    8. Review rule drift and Hit Confidence Trend auditing.
    9. Detection and prevention of tampered mutation events.
    """
    db_file = tmp_path / "ironledger_integrated.db"
    conn = connect(db_file)
    config_dir = tmp_path / "config"
    secret = "production-governance-secret-key-2026"
    _setup_safe_mode_config(config_dir, enabled=True, secret=secret)
    ledger_dir = _setup_ledger_dir(tmp_path)

    # ------------------------------------------------------------------------
    # Step 1: Pre-flight schema migration
    # ------------------------------------------------------------------------
    schema_ver = migrate_governed(conn)
    assert schema_ver >= 6
    assert verify_schema_checksums(conn) is True

    # ------------------------------------------------------------------------
    # Step 2: Safe Mode rejection of unauthorized mutation request
    # ------------------------------------------------------------------------
    initial_manifest = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert safe_mode_enabled(config_dir) is True

    with pytest.raises(SafeModeAuthorizationError, match="safe mode is active"):
        require_governed_authorization(
            conn,
            token=None,
            scope="compile",
            target_digest=initial_manifest,
            config_dir=config_dir,
            actor="operator_1",
        )

    # Denial audit event logged
    denied_row = conn.execute(
        "SELECT actor, action, result FROM audit_events WHERE result = 'denied' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert denied_row is not None
    assert denied_row[0] == "operator_1"
    assert denied_row[2] == "denied"

    # ------------------------------------------------------------------------
    # Step 3: Issue and verify valid HMAC step-up token
    # ------------------------------------------------------------------------
    step_up_token = create_step_up_token(
        secret,
        actor="lead_auditor",
        scope="compile",
        target_digest=initial_manifest,
        ttl_seconds=300,
    )
    auth_ok = require_governed_authorization(
        conn,
        token=step_up_token,
        scope="compile",
        target_digest=initial_manifest,
        config_dir=config_dir,
        actor="lead_auditor",
    )
    assert auth_ok["authorized"] is True
    assert auth_ok["mechanism"] == "token"

    auth_row = conn.execute(
        "SELECT actor, action, result FROM audit_events WHERE result = 'ok' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert auth_row[0] == "lead_auditor"
    assert "authorize compile (step-up)" in auth_row[1]

    # ------------------------------------------------------------------------
    # Step 4: Perform ledger compilation and append mutation #1
    # ------------------------------------------------------------------------
    main_bc = ledger_dir / "main.beancount"
    main_bc.write_text(
        main_bc.read_text(encoding="utf-8")
        + '2026-01-05 * "Salary deposit"\n'
        '  Assets:Bank:Checking  3500.00 USD\n'
        '  Income:Salary\n',
        encoding="utf-8",
    )
    manifest_post_comp1 = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert manifest_post_comp1 != initial_manifest

    mut_event_1 = append_mutation_event(
        conn,
        operator_session="sess_compile_wave1",
        action="compile",
        staged_count=1,
        rules_applied=1,
        rules_created=0,
        sha256_before=initial_manifest,
        sha256_after=manifest_post_comp1,
        ts_utc="2026-09-09T14:00:00Z",
    )
    assert mut_event_1.seq == 1
    assert mut_event_1.prev_mutation_hash == GENESIS_MUTATION_PREV_HASH

    # ------------------------------------------------------------------------
    # Step 5: Second authorized compilation and append mutation #2
    # ------------------------------------------------------------------------
    token_comp2 = create_step_up_token(
        secret,
        actor="lead_auditor",
        scope="compile",
        target_digest=manifest_post_comp1,
        ttl_seconds=300,
    )
    require_governed_authorization(
        conn,
        token=token_comp2,
        scope="compile",
        target_digest=manifest_post_comp1,
        config_dir=config_dir,
        actor="lead_auditor",
    )

    main_bc.write_text(
        main_bc.read_text(encoding="utf-8")
        + '2026-01-06 * "Office supplies"\n'
        '  Expenses:Supplies  45.00 USD\n'
        '  Assets:Bank:Checking\n',
        encoding="utf-8",
    )
    manifest_post_comp2 = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert manifest_post_comp2 != manifest_post_comp1

    mut_event_2 = append_mutation_event(
        conn,
        operator_session="sess_compile_wave2",
        action="compile",
        staged_count=1,
        rules_applied=1,
        rules_created=1,
        sha256_before=manifest_post_comp1,
        sha256_after=manifest_post_comp2,
        ts_utc="2026-09-09T15:00:00Z",
    )
    assert mut_event_2.seq == 2
    assert mut_event_2.prev_mutation_hash == mut_event_1.mutation_hash

    # ------------------------------------------------------------------------
    # Step 6: Verify unbroken cryptographic mutation chain
    # ------------------------------------------------------------------------
    chain_status = verify_mutation_chain(conn)
    assert chain_status.is_valid is True
    assert chain_status.mutation_count == 2
    assert chain_status.head_hash == mut_event_2.mutation_hash

    # ------------------------------------------------------------------------
    # Step 7: Build projection database and evaluate freshness SLA
    # ------------------------------------------------------------------------
    proj_db = tmp_path / "projection_integrated.sqlite"
    built_at_utc = "2026-09-09T15:00:01Z"
    with sqlite3.connect(str(proj_db)) as pconn:
        pconn.execute(
            """
            CREATE TABLE projection_meta (
                singleton INTEGER PRIMARY KEY,
                built_at_utc TEXT NOT NULL,
                ledger_output_hash TEXT NOT NULL
            ) STRICT
            """
        )
        pconn.execute(
            "INSERT INTO projection_meta (singleton, built_at_utc, ledger_output_hash) VALUES (1, ?, ?)",
            (built_at_utc, manifest_post_comp2),
        )
        pconn.commit()

    # Fresh SLA check (evaluated 2s after build)
    sla_fresh = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T15:00:03Z",
    )
    assert sla_fresh.status == FreshnessTier.FRESH
    assert sla_fresh.source_hash_match is True
    assert sla_fresh.latency_seconds == 2.0

    # Stale SLA check (evaluated 20s after build)
    sla_stale = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T15:00:21Z",
    )
    assert sla_stale.status == FreshnessTier.STALE

    # Critical SLA check (evaluated 60s after build)
    sla_crit = check_projection_db_freshness(
        proj_db,
        ledger_dir,
        now_utc="2026-09-09T15:01:01Z",
    )
    assert sla_crit.status == FreshnessTier.CRITICAL

    # ------------------------------------------------------------------------
    # Step 8: Audit rule drift and HCT metrics
    # ------------------------------------------------------------------------
    conn.execute(
        "INSERT INTO categorization_rules "
        "(rule_id, match_type, pattern, target_account, priority, active, created_at_utc) "
        "VALUES ('rule_salary', 'prefix', 'Salary', 'Income:Salary', 100, 1, '2026-01-01T00:00:00Z')"
    )
    # Add 10 successful hits and 0 overrides
    for i in range(10):
        append_audit_event(
            conn,
            actor="system",
            action="review auto-match (Income:Salary; rule rule_salary)",
            target=f"stx_sal_{i}",
            result="ok",
            ts_utc="2026-09-09T15:00:00Z",
        )
    conn.commit()

    drift_report = audit_all_rules_drift(conn, now_utc="2026-09-09T15:00:00Z")
    assert len(drift_report) == 1
    salary_rule_metrics = drift_report[0]
    assert salary_rule_metrics.rule_id == "rule_salary"
    assert salary_rule_metrics.hits_total == 10
    assert salary_rule_metrics.overrides_total == 0
    assert salary_rule_metrics.hct == 1.0
    assert salary_rule_metrics.tier == RuleHealthTier.HEALTHY
    assert salary_rule_metrics.provisional is False

    # ------------------------------------------------------------------------
    # Step 9: Tamper with mutation chain and assert verification fails
    # ------------------------------------------------------------------------
    conn.execute("DROP TRIGGER IF EXISTS mutation_events_no_update")
    conn.execute("UPDATE mutation_events SET sha256_after = ? WHERE seq = 1", ("9" * 64,))
    with pytest.raises(MutationVerificationError, match="hash mismatch"):
        verify_mutation_chain(conn)

    conn.close()
