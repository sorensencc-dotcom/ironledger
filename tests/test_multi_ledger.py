"""Tests for Phase 8 Task 8.3: Multi-Ledger Topology & Isolated Staging Queues."""

import os
import sqlite3
from pathlib import Path

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ledger.models import (
    LedgerTopology,
    TenantStagingQueue,
    LedgerAccountMapping,
    ConsolidatedBalanceSheet,
)
from ironledger.ledger.topology import LedgerRegistry
from ironledger.ledger.staging import StagingManager
from ironledger.ledger.consolidation import ConsolidationEngine
from ironledger.valuation.engine import ValuationEngine
from ironledger.valuation.models import PriceDirective


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "multi_ledger.db"
    conn = connect(str(db))
    migrations.migrate(conn)
    return conn


@pytest.fixture
def registry(conn, tmp_path):
    base = tmp_path / "ledgers"
    base.mkdir(parents=True, exist_ok=True)
    return LedgerRegistry(conn=conn, base_path=base)


@pytest.fixture
def staging(registry):
    return StagingManager(registry=registry)


@pytest.fixture
def consolidation(registry):
    return ConsolidationEngine(registry=registry)


def test_tenant_boundary_isolation(registry, staging):
    # Create two ledgers
    a = registry.create_ledger(
        name="Tenant A",
        root_account="Assets",
        base_currency="USD",
        storage_root="tenant_a",
    )
    b = registry.create_ledger(
        name="Tenant B",
        root_account="Assets",
        base_currency="EUR",
        storage_root="tenant_b",
    )

    # Stage operations in A only
    staging.enqueue(a.ledger_id, {"op": "post", "amount": 100})
    # Ensure B has an empty queue
    assert staging.peek(b.ledger_id) == []
    # Ensure A has the enqueued operation
    assert len(staging.peek(a.ledger_id)) == 1
    assert staging.peek(a.ledger_id)[0]["operation"]["amount"] == 100

    # Dequeue operation for A
    deq = staging.dequeue(a.ledger_id)
    assert deq is not None
    assert deq["operation"]["amount"] == 100
    assert deq["status"] == "processed"

    # Now A has no pending operations
    assert staging.peek(a.ledger_id) == []
    assert staging.dequeue(a.ledger_id) is None


def test_independent_compile_locks(tmp_path, registry):
    a = registry.create_ledger(
        name="Tenant A",
        root_account="Assets",
        base_currency="USD",
        storage_root="tenant_a",
    )
    b = registry.create_ledger(
        name="Tenant B",
        root_account="Assets",
        base_currency="EUR",
        storage_root="tenant_b",
    )

    lock_a = registry.get_lock_path(a.ledger_id)
    lock_b = registry.get_lock_path(b.ledger_id)

    with registry.acquire_compile_lock(a.ledger_id):
        assert lock_a.exists()
        # Acquiring B's lock concurrently must succeed
        with registry.acquire_compile_lock(b.ledger_id):
            assert lock_b.exists()


def test_path_traversal_symlink_escape_rejected(tmp_path, registry):
    base = tmp_path / "ledgers"
    base.mkdir(parents=True, exist_ok=True)
    evil = tmp_path / "evil"
    evil.mkdir(parents=True, exist_ok=True)

    # Symlink pointing outside base
    symlink = base / "escape"
    try:
        symlink.symlink_to(evil)
        with pytest.raises(ValueError):
            registry.register_storage_root(
                ledger_id="tenant_evil",
                storage_root=symlink,
            )
    except (OSError, NotImplementedError):
        # On Windows without developer mode/admin symlinks may raise OSError
        # Test relative traversal instead
        with pytest.raises(ValueError):
            registry.register_storage_root(
                ledger_id="tenant_evil",
                storage_root="../../outside",
            )


def test_path_traversal_relative_dotdot_rejected(registry):
    with pytest.raises(ValueError):
        registry.create_ledger(
            name="Escape Tenant",
            storage_root="../outside_dir",
        )


def test_ledger_lookup_and_listing(registry):
    l1 = registry.create_ledger(name="L1", ledger_id="corp_1")
    l2 = registry.create_ledger(name="L2", ledger_id="corp_2")

    fetched = registry.get_ledger("corp_1")
    assert fetched is not None
    assert fetched.name == "L1"
    assert fetched.base_currency == "USD"

    assert registry.get_ledger("nonexistent_ledger") is None

    all_ledgers = registry.list_ledgers()
    ids = [l.ledger_id for l in all_ledgers]
    assert "default" in ids
    assert "corp_1" in ids
    assert "corp_2" in ids


def test_consolidated_balance_reporting(consolidation, registry, conn):
    a = registry.create_ledger(
        name="Tenant A",
        root_account="Assets",
        base_currency="USD",
        storage_root="tenant_a",
    )
    b = registry.create_ledger(
        name="Tenant B",
        root_account="Assets",
        base_currency="EUR",
        storage_root="tenant_b",
    )

    # Seed rate for EUR -> USD (1.10 = 11/10)
    val_engine = ValuationEngine(conn)
    val_engine.add_price_directive(
        PriceDirective(
            directive_date="2026-09-01",
            base_currency="EUR",
            quote_currency="USD",
            rate_numerator=11,
            rate_denominator=10,
            ledger_id=b.ledger_id,
        )
    )

    # Seed some balances
    consolidation.seed_balance(a.ledger_id, "Assets:Cash", 10_000, "USD", 2)
    consolidation.seed_balance(b.ledger_id, "Assets:Cash", 5_000, "EUR", 2)

    sheet = consolidation.consolidated_balance_sheet(base_currency="USD", as_of_date="2026-09-05")
    assert isinstance(sheet, ConsolidatedBalanceSheet)
    # Expect both entities represented in the consolidated view
    assert {"Tenant A", "Tenant B"}.issubset({e.name for e in sheet.entities})
    # Total USD = 100.00 USD (10000 minor) + 50.00 EUR * 1.10 = 55.00 USD (5500 minor) = 15500 minor ($155.00)
    assert sheet.total_minor == 15500


def test_foreign_key_cascade_deletion(registry, staging, consolidation, conn):
    tenant = registry.create_ledger(name="Ephemeral Tenant", ledger_id="ephemeral_1")
    staging.enqueue(tenant.ledger_id, {"op": "test"})
    consolidation.seed_balance(tenant.ledger_id, "Assets:Bank", 5000, "USD", 2)

    assert len(staging.peek(tenant.ledger_id)) == 1

    # Delete the ledger; foreign keys ON should cascade delete operations and balances
    conn.execute("DELETE FROM ledgers WHERE ledger_id = ?", (tenant.ledger_id,))
    conn.commit()

    assert staging.peek(tenant.ledger_id) == []
    cur = conn.execute("SELECT COUNT(*) FROM ledger_balances WHERE ledger_id = ?", (tenant.ledger_id,))
    assert cur.fetchone()[0] == 0
