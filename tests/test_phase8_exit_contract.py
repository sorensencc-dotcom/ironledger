"""Phase 8 Exit-Gate Contract & Acceptance Regression Suite.

Verifies:
1. Static analysis AST visitor guard ensuring ZERO runtime beancount imports and ZERO float division in valuation/manifests.
2. Positive and negative test fixtures verifying AST scanner detection fidelity.
3. Multi-Asset Valuation Engine & Price Directives Cache (Task 8.1).
4. Bi-directional Lineage DAG & Cycle Prevention (Task 8.2).
5. Multi-Ledger Topology & Isolated Staging Queues (Task 8.3).
6. Deterministic Audit Replay & Point-in-Time Engine (Task 8.4).
7. Scoped Capability Tokens & RBAC Policy Enforcement (Task 8.5).
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from ironledger.auth import (
    PROTECTED_OPERATIONS,
    ROLE_CEILINGS,
    CapabilityToken,
    InsufficientScopeError,
    InvalidRoleCeilingError,
    InvalidTokenError,
    MalformedTokenError,
    PolicyEnforcer,
    Role,
    TenantAccessDeniedError,
    TokenExpiredError,
    TokenRevokedError,
    UnauthorizedError,
    create_capability_token,
    get_capability_token_by_id,
    list_capability_tokens,
    revoke_capability_token,
)
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ledger.consolidation import ConsolidationEngine
from ironledger.ledger.models import ConsolidatedBalanceSheet, LedgerTopology
from ironledger.ledger.staging import StagingManager
from ironledger.ledger.topology import LedgerRegistry
from ironledger.lineage import (
    LineageCycleError,
    LineageDAG,
    LineageEdge,
    LineageExplorer,
    LineageNode,
    NodeType,
    RelationshipType,
)
from ironledger.manifests import (
    GENESIS_MANIFEST_HASH,
    compute_directory_manifest_hash,
    compute_ledger_manifest_hash,
)
from ironledger.replay.anchors import (
    compute_anchor_signature_digest,
    read_trust_anchor,
    sign_authority_payload,
    verify_authority_signature,
    write_trust_anchor,
)
from ironledger.replay.engine import (
    apply_mutation_and_append,
    reconcile_manifest_on_startup,
    replay_audit_stream,
)
from ironledger.replay.models import (
    AuditTamperDetectedError,
    MutationPayload,
    TrustAnchor,
)
from ironledger.replay.snapshot import GENESIS_PROJECTION_HASH, compute_projection_hash
from ironledger.valuation.engine import ValuationEngine
from ironledger.valuation.formatting import (
    format_beancount_price_directive,
    format_minor_units,
)
from ironledger.valuation.models import (
    MissingPriceDirectiveError,
    PriceDirective,
    StalePriceDirectiveError,
    ValuationError,
)


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
        # Check __import__('beancount') or importlib.import_module('beancount')
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

        # Check getattr(importlib, "import_module")("beancount")
        if isinstance(func, ast.Call) and isinstance(func.func, ast.Name) and func.func.id == "getattr":
            if func.args and len(func.args) >= 2:
                attr_name = func.args[1]
                if isinstance(attr_name, ast.Constant) and attr_name.value == "import_module":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        target = node.args[0].value
                        if target == "beancount" or target.startswith("beancount."):
                            self.violations.append(
                                f"Dynamic getattr import of '{target}' at line {node.lineno}"
                            )

        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if self.check_div and isinstance(node.op, ast.Div):
            # Check if this is a pathlib Path / "filename" concatenation
            is_path_join = False
            if isinstance(node.right, (ast.Constant, ast.JoinedStr)):
                is_path_join = True
            elif isinstance(node.left, (ast.Constant, ast.JoinedStr)):
                is_path_join = True
            elif isinstance(node.right, ast.Attribute) and node.right.attr in ("name", "path", "filename", "stem"):
                is_path_join = True
            elif isinstance(node.left, ast.Name) and any(kw in node.left.id.lower() for kw in ("dir", "path", "root", "base")):
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

    bad_dynamic_import = "import importlib\nmod = importlib.import_module('beancount.parser')"
    scanner = BeancountAndFloatAstScanner(check_div=False)
    scanner.visit(ast.parse(bad_dynamic_import))
    assert len(scanner.violations) >= 1

    bad_float_div = "def calculate_price(n, d):\n    return n / d\n"
    scanner = BeancountAndFloatAstScanner(check_div=True)
    scanner.visit(ast.parse(bad_float_div))
    assert len(scanner.violations) >= 1

    good_integer_math = "def calculate_price(n, d):\n    return n // d, n % d\n"
    scanner = BeancountAndFloatAstScanner(check_div=True)
    scanner.visit(ast.parse(good_integer_math))
    assert len(scanner.violations) == 0


def test_src_tree_ast_zero_beancount_and_zero_float_guard():
    """Scan entire src/ironledger codebase ensuring zero runtime beancount imports and zero float division in valuation/manifests."""
    src_root = Path(__file__).resolve().parent.parent / "src" / "ironledger"
    assert src_root.exists() and src_root.is_dir()

    all_violations: list[str] = []

    for py_file in src_root.rglob("*.py"):
        rel_path = py_file.relative_to(src_root.parent)
        is_valuation_or_manifest = (
            "valuation" in py_file.parts
            or py_file.name in ("manifests.py", "formatting.py")
            or "replay" in py_file.parts
        )
        code = py_file.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(py_file))
        scanner = BeancountAndFloatAstScanner(check_div=is_valuation_or_manifest)
        scanner.visit(tree)

        for v in scanner.violations:
            all_violations.append(f"{rel_path}: {v}")

    assert not all_violations, f"AST Violations found:\n" + "\n".join(all_violations)


# ============================================================================
# 2. Phase 8 Acceptance Fixtures & End-to-End Exit Contract
# ============================================================================

@pytest.fixture
def exit_env(tmp_path):
    db_path = tmp_path / "phase8_exit.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    beancount_root = tmp_path / "beancount_data"
    beancount_root.mkdir(parents=True, exist_ok=True)
    return conn, beancount_root


def test_phase8_e2e_exit_contract(exit_env):
    """End-to-end integration test exercising all Phase 8 capabilities together."""
    conn, beancount_root = exit_env

    # 1. Multi-Ledger Topology Setup (Task 8.3)
    registry = LedgerRegistry(conn=conn, base_path=beancount_root)
    alpha = registry.create_ledger("Alpha Fund", "Assets:Alpha", "USD", "alpha_fund", ledger_id="alpha_fund")
    beta = registry.create_ledger("Beta Treasury", "Assets:Beta", "EUR", "beta_treasury", ledger_id="beta_treasury")
    assert alpha.ledger_id == "alpha_fund"
    assert beta.ledger_id == "beta_treasury"

    # 2. RBAC Capability Tokens (Task 8.5)
    raw_admin, tok_admin = create_capability_token(conn, Role.ADMIN, None, is_global=True)
    raw_operator_a, tok_op_a = create_capability_token(conn, Role.OPERATOR, "alpha_fund")
    raw_reader_a, tok_rd_a = create_capability_token(conn, Role.READER, "alpha_fund")

    # Verify authorization policies
    PolicyEnforcer.authorize(conn, raw_admin, "*", None)
    PolicyEnforcer.authorize(conn, raw_operator_a, "staging:write", "alpha_fund")
    PolicyEnforcer.authorize(conn, raw_reader_a, "ledger:read", "alpha_fund")
    with pytest.raises(TenantAccessDeniedError):
        PolicyEnforcer.authorize(conn, raw_operator_a, "staging:write", "beta_treasury")

    # 3. Outbox Promotion & Mutation Append with External HMAC Anchor (Task 8.4)
    reconcile_manifest_on_startup(conn, beancount_root)

    evt1, p1 = apply_mutation_and_append(
        conn=conn,
        beancount_root=beancount_root,
        ledger_id="alpha_fund",
        operator_session="sess_exit",
        action="price_directive",
        event_type="PRICE_DIRECTIVE",
        payload={
            "id": 1,
            "directive_date": "2026-09-10",
            "base_currency": "BTC",
            "quote_currency": "USD",
            "rate_numerator": 65000,
            "rate_denominator": 1,
            "precision_scale": 4,
            "source": "EXCHANGE_API",
        },
    )
    assert evt1["seq"] == 1
    assert p1.authority_signature is not None

    # Verify external trust anchor file
    anchor = read_trust_anchor(beancount_root, "alpha_fund")
    assert anchor.seq == 1
    assert anchor.mutation_id == evt1["mutation_id"]

    # 4. Multi-Asset Valuation & Price Directives (Task 8.1)
    val_engine = ValuationEngine(conn=conn)
    # Convert 1.5 BTC (150,000,000 minor units, scale 8) to USD (scale 2)
    # 1.5 * 65000 = 97,500.00 USD (9,750,000 minor units)
    converted_usd = val_engine.convert(
        source_minor=150_000_000,
        source_scale=8,
        base_currency="BTC",
        quote_currency="USD",
        as_of_date="2026-09-10",
        target_scale=2,
        ledger_id="alpha_fund",
    )
    assert converted_usd == 9_750_000

    # Format Beancount price directive with zero float drift
    bean_directive = format_beancount_price_directive(
        "2026-09-10",
        "BTC",
        "USD",
        65000,
        1,
        4,
    )
    assert bean_directive == "2026-09-10 price BTC 65000.0000 USD"

    # 5. Bi-Directional Lineage DAG & Cycle Prevention (Task 8.2)
    dag = LineageDAG(conn)
    dag.add_node(LineageNode(node_id="ev_001", node_type="EVIDENCE_BLOB", entity_ref="SHA256:abc", ledger_id="alpha_fund"))
    dag.add_node(LineageNode(node_id="src_001", node_type="SOURCE_RECORD", entity_ref="RAW_CSV", ledger_id="alpha_fund"))
    dag.add_node(LineageNode(node_id="stg_001", node_type="STAGED_TX", entity_ref="STAGED", ledger_id="alpha_fund"))
    dag.add_node(LineageNode(node_id="pst_001", node_type="POSTING", entity_ref="Assets:Alpha:BTC", ledger_id="alpha_fund"))

    dag.add_edge(ledger_id="alpha_fund", source_node_id="ev_001", target_node_id="src_001", relationship="EXTRACTED_FROM")
    dag.add_edge(ledger_id="alpha_fund", source_node_id="src_001", target_node_id="stg_001", relationship="COMPILED_INTO")
    dag.add_edge(ledger_id="alpha_fund", source_node_id="stg_001", target_node_id="pst_001", relationship="COMPILED_INTO")

    # Self-edge rejection
    with pytest.raises(LineageCycleError):
        dag.add_edge(ledger_id="alpha_fund", source_node_id="ev_001", target_node_id="ev_001", relationship="EXTRACTED_FROM")

    # Cycle prevention rejection
    with pytest.raises(LineageCycleError):
        dag.add_edge(ledger_id="alpha_fund", source_node_id="pst_001", target_node_id="ev_001", relationship="COMPILED_INTO")

    explorer = LineageExplorer(conn)
    # Downstream lineage trace: ev_001 -> pst_001
    downstream_trace = explorer.trace_downstream("alpha_fund", "ev_001")
    assert "pst_001" in [n.node_id for n in downstream_trace.nodes]

    # Upstream provenance trace: pst_001 -> ev_001
    upstream_trace = explorer.trace_upstream("alpha_fund", "pst_001")
    assert "ev_001" in [n.node_id for n in upstream_trace.nodes]

    # 6. Point-in-Time Deterministic Audit Replay (Task 8.4)
    rep_result = replay_audit_stream(
        live_conn=conn,
        beancount_root=beancount_root,
        target_ledger_id="alpha_fund",
    )
    assert rep_result.report.replay_success is True
    assert rep_result.report.target_ledger_events_replayed == 1
    assert rep_result.report.final_projection_hash == p1.projection_hash_after

    # 7. Multi-Entity Consolidated Balance Sheet (Task 8.3)
    conn.execute(
        "INSERT INTO ledger_balances (ledger_id, account, amount_minor, currency, scale) VALUES (?, ?, ?, ?, ?)",
        ("alpha_fund", "Assets:Alpha:BTC", 150000000, "BTC", 8),
    )
    conn.execute(
        "INSERT INTO ledger_balances (ledger_id, account, amount_minor, currency, scale) VALUES (?, ?, ?, ?, ?)",
        ("beta_treasury", "Assets:Beta:EUR", 500000, "EUR", 2),
    )
    conn.commit()

    val_engine.add_price_directive(
        PriceDirective(
            directive_date="2026-09-10",
            base_currency="EUR",
            quote_currency="USD",
            rate_numerator=11,
            rate_denominator=10,
            precision_scale=4,
            source="POLLED_FEED",
            ledger_id="beta_treasury",
        )
    )

    consolidation = ConsolidationEngine(registry=registry)
    sheet = consolidation.consolidated_balance_sheet(
        base_currency="USD",
        as_of_date="2026-09-10",
    )
    assert sheet.base_currency == "USD"
    # alpha: 97,500.00 USD (9,750,000 minor units)
    # beta: 5,000.00 EUR * 1.1 = 5,500.00 USD (550,000 minor units)
    # Total: 103,000.00 USD (10,300,000 minor units)
    assert sheet.total_minor == 10_300_000
