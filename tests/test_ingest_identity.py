"""Phase 2a: versioned identity fingerprint and FITID method selection."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.identity import (
    IDENTITY_ALGO_VERSION,
    canonical_payee,
    fingerprint,
    select_identity_method,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_algo_version_is_one():
    assert IDENTITY_ALGO_VERSION == 1


def test_canonical_payee_order_nfc_then_casefold_then_collapse():
    assert canonical_payee("  Café   NOIR  ") == "café noir"


@pytest.mark.parametrize("payee", ["COFFEE BAR", "coffee   bar", "  Coffee Bar\t"])
def test_fingerprint_is_stable_across_payee_whitespace_and_case(payee: str):
    base = dict(
        account="Assets:Bank:Checking:B", iso_date="2026-08-15", minor_units=-1299,
        currency="USD", institution_account_key="b/c1",
    )
    assert fingerprint(payee="COFFEE BAR", **base) == fingerprint(payee=payee, **base)


def test_fingerprint_changes_with_institution_account_key():
    base = dict(
        account="Assets:Bank:Checking:B", iso_date="2026-08-15", minor_units=-1299,
        currency="USD", payee="COFFEE BAR",
    )
    assert fingerprint(institution_account_key="b/c1", **base) != fingerprint(
        institution_account_key="b/c2", **base
    )


def test_method_is_fallback_without_a_trust_row(db: sqlite3.Connection):
    assert select_identity_method(db, "b", "c1", has_fitid=True) == "sha256_fallback"


def test_method_is_fitid_with_a_trust_row_and_a_fitid(db: sqlite3.Connection):
    db.execute(
        "INSERT INTO fitid_trust_records (institution_id, account_id, added_at_utc, note) "
        "VALUES ('b', 'c1', '2026-09-02T10:00:00Z', '')"
    )
    db.commit()
    assert select_identity_method(db, "b", "c1", has_fitid=True) == "fitid"
    assert select_identity_method(db, "b", "c1", has_fitid=False) == "sha256_fallback"
