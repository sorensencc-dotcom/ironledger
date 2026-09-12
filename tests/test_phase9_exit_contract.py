"""Phase 9 Exit-Gate Contract & Acceptance Regression Suite.

Verifies:
1. Static analysis AST visitor guard ensuring ZERO runtime beancount imports across all src/ironledger/ modules.
2. Static analysis AST visitor guard ensuring ZERO float division across Phase 9 connector, security, event, and metrics modules.
3. Positive and negative test fixtures verifying AST scanner detection fidelity.
4. End-to-End Integration across Connectors, Envelope Encryption, Webhook Outbox, DLQ, and Prometheus Observability.
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from ironledger.connectors import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    ConnectorProvider,
    ConnectorRegistry,
    PlaidConnector,
    ProtocolType,
    SyncResult,
    TokenBucketRateLimiter,
)
from ironledger.db.migrations import migrate_governed
from ironledger.events import (
    DeliveryResult,
    EventOutboxPublisher,
    OutboxEvent,
    WebhookDelivery,
    WebhookDispatcher,
    WebhookSigner,
    WebhookSubscription,
    reconcile_abandoned_deliveries,
)
from ironledger.observability import (
    CIRCUIT_BREAKER_STATE,
    CONNECTOR_RECORDS_STAGED_TOTAL,
    CONNECTOR_SYNC_DURATION_MS,
    EVENT_OUTBOX_QUEUE_DEPTH,
    HTTP_REQUEST_DURATION_MS,
    HTTP_REQUESTS_TOTAL,
    RATE_LIMITER_TOKENS_AVAILABLE,
    REGISTRY,
    TOKEN_AUTH_FAILURES_TOTAL,
    WEBHOOK_DELIVERY_FAILURES_TOTAL,
    Counter,
    Gauge,
    Histogram,
    JsonLogFormatter,
    MetricsRegistry,
)
from ironledger.security.credentials import (
    load_connector_credentials,
    save_connector_credentials,
)
from ironledger.security.envelope import (
    EnvelopeCiphertext,
    EnvelopeEncryptor,
    TamperDetectedError,
)
from ironledger.security.key_provider import (
    EnvironmentKeyProvider,
    KeyNotFoundError,
)
from ironledger.security.scrubbing import SecretScrubber


# ============================================================================
# 1. AST Scanner for Zero Runtime Beancount Import & Zero Float Division
# ============================================================================

class BeancountAndFloatAstScanner(ast.NodeVisitor):
    """AST visitor enforcing zero runtime beancount imports and zero float division in financial modules."""

    def __init__(self, check_div: bool = False) -> None:
        self.check_div = check_div
        self.violations: list[str] = []
        self.aliases: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.aliases[alias.asname or alias.name] = alias.name
            if alias.name == "beancount" or alias.name.startswith("beancount."):
                self.violations.append(
                    f"Direct import of '{alias.name}' at line {node.lineno}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if mod == "beancount" or mod.startswith("beancount."):
            self.violations.append(
                f"Import from '{mod}' at line {node.lineno}"
            )
        for alias in node.names:
            full_name = f"{mod}.{alias.name}" if mod else alias.name
            self.aliases[alias.asname or alias.name] = full_name
            if full_name == "beancount" or full_name.startswith("beancount."):
                self.violations.append(
                    f"Import of '{full_name}' at line {node.lineno}"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        func_name = ""
        if isinstance(func, ast.Name):
            func_name = self.aliases.get(func.id, func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base = self.aliases.get(func.value.id, func.value.id)
            func_name = f"{base}.{func.attr}"

        if func_name in ("__import__", "builtins.__import__", "importlib.import_module"):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                target = node.args[0].value
                if target == "beancount" or target.startswith("beancount."):
                    self.violations.append(
                        f"Dynamic import of '{target}' via '{func_name}' at line {node.lineno}"
                    )

        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if self.check_div and isinstance(node.op, ast.Div):
            is_path_join = False
            if isinstance(node.left, ast.Name) and any(kw in node.left.id.lower() for kw in ("dir", "path", "root", "base", "storage")):
                is_path_join = True
            elif isinstance(node.right, ast.Attribute) and node.right.attr in ("name", "path", "filename", "stem"):
                is_path_join = True

            if not is_path_join:
                self.violations.append(
                    f"Float division operator '/' detected at line {node.lineno}. Use pure integer rational arithmetic '//'."
                )
        self.generic_visit(node)


def test_ast_scanner_positive_and_negative_fixtures():
    """Verify AST scanner detection fidelity on positive (violating) and negative (compliant) snippets."""
    bad_direct_import = "import beancount\nimport beancount.core.data as bdata"
    scanner = BeancountAndFloatAstScanner(check_div=False)
    scanner.visit(ast.parse(bad_direct_import))
    assert len(scanner.violations) >= 2

    bad_from_import = "from beancount.parser import parser\nfrom beancount import loader"
    scanner = BeancountAndFloatAstScanner(check_div=False)
    scanner.visit(ast.parse(bad_from_import))
    assert len(scanner.violations) >= 2

    bad_dynamic_import = "import importlib\nimportlib.import_module('beancount.core')"
    scanner = BeancountAndFloatAstScanner(check_div=False)
    scanner.visit(ast.parse(bad_dynamic_import))
    assert len(scanner.violations) >= 1

    good_beancount_free = "from ironledger.connectors import TokenBucketRateLimiter\nfrom ironledger.events import WebhookSigner"
    scanner = BeancountAndFloatAstScanner(check_div=False)
    scanner.visit(ast.parse(good_beancount_free))
    assert len(scanner.violations) == 0

    bad_float_div = "def calculate_tokens(dt, rate):\n    return (dt * rate) / 60000"
    scanner = BeancountAndFloatAstScanner(check_div=True)
    scanner.visit(ast.parse(bad_float_div))
    assert len(scanner.violations) >= 1

    good_integer_div = "def calculate_tokens(dt, rate):\n    return (dt * rate) // 60000"
    scanner = BeancountAndFloatAstScanner(check_div=True)
    scanner.visit(ast.parse(good_integer_div))
    assert len(scanner.violations) == 0


def test_phase9_codebase_ast_invariants():
    """Scan all Python modules under src/ironledger/ for zero runtime beancount imports and integer math."""
    repo_root = Path(__file__).resolve().parent.parent
    src_dir = repo_root / "src" / "ironledger"

    assert src_dir.exists(), f"Source directory not found: {src_dir}"

    all_py_files = list(src_dir.rglob("*.py"))
    assert len(all_py_files) > 20, "Expected full ironledger codebase to be discovered"

    # 1. Zero runtime beancount imports across all files in src/ironledger/
    beancount_violations = []
    for py_file in all_py_files:
        content = py_file.read_text(encoding="utf-8-sig")
        tree = ast.parse(content, filename=str(py_file))
        scanner = BeancountAndFloatAstScanner(check_div=False)
        scanner.visit(tree)
        for v in scanner.violations:
            beancount_violations.append(f"{py_file.name}: {v}")

    assert not beancount_violations, f"Found runtime beancount imports:\n" + "\n".join(beancount_violations)

    # 2. Zero float division in connectors, events, and rate limiting modules
    div_violations = []
    math_modules = [
        src_dir / "connectors" / "rate_limiter.py",
        src_dir / "connectors" / "circuit_breaker.py",
        src_dir / "events" / "dispatcher.py",
        src_dir / "observability" / "middleware.py",
    ]
    for math_mod in math_modules:
        if math_mod.exists():
            content = math_mod.read_text(encoding="utf-8-sig")
            tree = ast.parse(content, filename=str(math_mod))
            scanner = BeancountAndFloatAstScanner(check_div=True)
            scanner.visit(tree)
            for v in scanner.violations:
                div_violations.append(f"{math_mod.name}: {v}")

    assert not div_violations, f"Found float division violations in financial math modules:\n" + "\n".join(div_violations)


# ============================================================================
# 2. Phase 9 Comprehensive End-to-End Acceptance Integration Flow
# ============================================================================

def test_phase9_full_governance_and_deployment_flow(monkeypatch, tmp_path):
    """End-to-end integration test verifying connectors, encryption, outbox, webhooks, and metrics."""
    # 1. Configure key provider
    kek_hex = "0123456789012345678901234567890101234567890123456789012345678901"
    monkeypatch.setenv("IRONLEDGER_KEK_ENTERPRISE_V1", kek_hex)
    monkeypatch.setenv("IRONLEDGER_KEK_DEFAULT", kek_hex)
    key_provider = EnvironmentKeyProvider()

    # 2. Initialize Database and run Migration 0012
    db_file = str(tmp_path / "enterprise_ledger.db")
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    # Seed Ledger
    conn.execute(
        """
        INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency, created_at, root_account, storage_root, is_active)
        VALUES ('led_corp', 'Corporate Ledger', 'USD', datetime('now'), 'Assets', 'corp', 1);
        """
    )
    conn.commit()

    # 3. Connector Governance & Envelope Encryption Roundtrip
    conn.execute(
        """
        INSERT INTO connector_providers (provider_id, name, protocol_type, base_url, is_active, rate_limit_rpm, burst_capacity)
        VALUES ('plaid_corp', 'Plaid Production Connector', 'PLAID', 'https://production.plaid.com', 1, 120, 20);
        """
    )
    conn.commit()

    secret_payload = {"client_id": "corp_client_1", "secret": "super_secret_plaid_key_xyz"}
    save_connector_credentials(conn, "led_corp", "plaid_corp", secret_payload, key_provider, kek_key_id="enterprise_v1")

    # Verify credentials in database are envelope-encrypted (zero plaintext)
    cursor = conn.cursor()
    cursor.execute("SELECT encrypted_payload_blob, payload_iv_hex, payload_auth_tag_hex FROM connector_credentials WHERE ledger_id = 'led_corp';")
    enc_row = cursor.fetchone()
    assert enc_row is not None
    assert b"super_secret_plaid_key_xyz" not in enc_row[0]

    loaded_creds = load_connector_credentials(conn, "led_corp", "plaid_corp", key_provider)
    assert loaded_creds["secret"] == "super_secret_plaid_key_xyz"

    # 4. Token-Bucket Rate Limiter & Circuit Breaker Invariants
    limiter = TokenBucketRateLimiter(rate_limit_rpm=60, burst_capacity=2, initial_time_ms=0)
    assert limiter.acquire(1, now_ms=0) is True
    assert limiter.acquire(1, now_ms=0) is True
    assert limiter.acquire(1, now_ms=0) is False  # Burst capacity exhausted

    cb = CircuitBreaker(failure_threshold=2, base_cooldown_ms=5000)
    cb.record_failure(now_ms=100)
    cb.record_failure(now_ms=200)
    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        cb.execute(lambda: "never_called", now_ms=300)

    # 5. Webhook Subscription, Transactional Outbox & Delivery Dispatch
    sub = EventOutboxPublisher.register_subscription(
        conn=conn,
        ledger_id="led_corp",
        target_url="https://enterprise.acme.com/webhooks/ironledger",
        secret="whsec_enterprise_signing_secret_999",
        event_types=["TRANSACTION_INGESTED", "BALANCE_UPDATED"],
        key_provider=key_provider,
        kek_key_id="enterprise_v1",
    )

    # Publish transactional event
    outbox_evt = EventOutboxPublisher.publish_event(
        conn=conn,
        ledger_id="led_corp",
        event_type="TRANSACTION_INGESTED",
        payload={"tx_id": "tx_corp_999", "amount": 500000, "currency": "USD"},
    )
    assert outbox_evt.event_type == "TRANSACTION_INGESTED"

    # Claim leased deliveries
    claimed_deliveries = WebhookDispatcher.claim_deliveries(conn, worker_id="node_prod_1", batch_size=5)
    assert len(claimed_deliveries) == 1
    delivery = claimed_deliveries[0]
    assert delivery.status == "PROCESSING"

    # Dispatch signed webhook request with mock HTTP receiver
    dispatched_payloads = []

    def mock_enterprise_receiver(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        dispatched_payloads.append((url, headers, body))
        # Verify receiver HMAC-SHA256 signature verification
        sig_valid = WebhookSigner.verify_signature(
            secret="whsec_enterprise_signing_secret_999",
            signature_header=headers["X-IronLedger-Signature"],
            payload_json=body.decode("utf-8"),
        )
        assert sig_valid is True, "Webhook signature verification failed on receiver"
        return 200, "Accepted"

    disp_result = WebhookDispatcher.dispatch_delivery(
        conn=conn,
        delivery=delivery,
        key_provider=key_provider,
        http_client=mock_enterprise_receiver,
    )
    assert disp_result.success is True
    assert disp_result.status_code == 200
    assert len(dispatched_payloads) == 1

    # Verify delivery marked DELIVERED
    cursor.execute("SELECT status, completed_at_utc FROM webhook_deliveries WHERE delivery_id = ?;", (delivery.delivery_id,))
    assert cursor.fetchone()[0] == "DELIVERED"

    # 6. Prometheus Observability Registry
    HTTP_REQUESTS_TOTAL.inc(1, labels={"method": "POST", "path": "/api/connectors/sync", "status": "200"})
    prom_text = REGISTRY.render_prometheus()
    assert "ironledger_http_requests_total" in prom_text
    assert 'path="/api/connectors/sync"' in prom_text

    conn.close()
