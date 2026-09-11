"""Tests for Phase 8 Task 8.1: Multi-Asset Valuation Engine & Price Directives Cache."""

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.valuation.models import (
    PriceDirective,
    ValuationError,
    MissingPriceDirectiveError,
    StalePriceDirectiveError,
)
from ironledger.valuation.formatting import (
    validate_calendar_date,
    format_minor_units,
    format_beancount_price_directive,
)
from ironledger.valuation.engine import (
    convert_amount_rational,
    ValuationEngine,
)


@pytest.fixture
def db_conn():
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


# ============================================================================
# 1. Exact Rational Conversion & Banker's Half-Even Rounding Tests
# ============================================================================


def test_convert_amount_rational_basic_same_scale():
    # 100 USD (scale 2 = 10000 minor) converted at 2/1 to EUR (scale 2) -> 20000 minor (200 EUR)
    result = convert_amount_rational(
        source_minor=10000,
        source_scale=2,
        rate_numerator=2,
        rate_denominator=1,
        target_scale=2,
    )
    assert result == 20000


def test_convert_amount_rational_mixed_scales():
    # 1 BTC (scale 8 = 100_000_000 minor) at rate 60000/1 USD (scale 2) -> 60_000.00 USD = 6_000_000 minor
    # 100_000_000 * 60000 * (10^2 / 10^8) = 100_000_000 * 60000 / 10^6 = 6,000,000 minor (60,000.00 USD)
    result = convert_amount_rational(
        source_minor=100_000_000,
        source_scale=8,
        rate_numerator=60_000,
        rate_denominator=1,
        target_scale=2,
    )
    assert result == 6_000_000


def test_convert_amount_rational_bankers_half_even_positive():
    # 5 / 2 = 2.5 -> rounds to 2 (nearest even)
    # source_minor=5, scale=0, rate=1/2, target_scale=0 -> 5/2 = 2.5 -> 2
    assert convert_amount_rational(5, 0, 1, 2, 0) == 2
    # 7 / 2 = 3.5 -> rounds to 4 (nearest even)
    assert convert_amount_rational(7, 0, 1, 2, 0) == 4
    # 9 / 2 = 4.5 -> rounds to 4 (nearest even)
    assert convert_amount_rational(9, 0, 1, 2, 0) == 4
    # 11 / 2 = 5.5 -> rounds to 6 (nearest even)
    assert convert_amount_rational(11, 0, 1, 2, 0) == 6


def test_convert_amount_rational_bankers_half_even_negative():
    # -5 / 2 = -2.5 -> rounds to -2
    assert convert_amount_rational(-5, 0, 1, 2, 0) == -2
    # -7 / 2 = -3.5 -> rounds to -4
    assert convert_amount_rational(-7, 0, 1, 2, 0) == -4
    # -9 / 2 = -4.5 -> rounds to -4
    assert convert_amount_rational(-9, 0, 1, 2, 0) == -4
    # -11 / 2 = -5.5 -> rounds to -6
    assert convert_amount_rational(-11, 0, 1, 2, 0) == -6


def test_convert_amount_rational_non_tie_rounding():
    # 2.4 (12/5) -> 2
    assert convert_amount_rational(12, 0, 1, 5, 0) == 2
    # 2.6 (13/5) -> 3
    assert convert_amount_rational(13, 0, 1, 5, 0) == 3
    # -2.4 -> -2
    assert convert_amount_rational(-12, 0, 1, 5, 0) == -2
    # -2.6 -> -3
    assert convert_amount_rational(-13, 0, 1, 5, 0) == -3


def test_convert_amount_rational_zero_and_precision_scale_zero():
    assert convert_amount_rational(0, 2, 100, 1, 0) == 0
    assert convert_amount_rational(0, 0, 100, 1, 0) == 0


@pytest.mark.parametrize(
    "invalid_arg",
    [
        {"source_minor": True},
        {"source_minor": False},
        {"source_minor": 1.5},
        {"source_minor": "100"},
        {"source_scale": -1},
        {"source_scale": 19},
        {"source_scale": 2.0},
        {"source_scale": True},
        {"rate_numerator": 0},
        {"rate_numerator": -5},
        {"rate_numerator": 1.5},
        {"rate_numerator": True},
        {"rate_denominator": 0},
        {"rate_denominator": -1},
        {"rate_denominator": 2.5},
        {"rate_denominator": False},
        {"target_scale": -1},
        {"target_scale": 19},
        {"target_scale": 2.0},
        {"target_scale": True},
    ],
)
def test_convert_amount_rational_strict_type_guards(invalid_arg):
    valid_kwargs = {
        "source_minor": 100,
        "source_scale": 2,
        "rate_numerator": 1,
        "rate_denominator": 1,
        "target_scale": 2,
    }
    valid_kwargs.update(invalid_arg)
    with pytest.raises(TypeError):
        convert_amount_rational(**valid_kwargs)


# ============================================================================
# 2. Formatting & Calendar Validation Tests
# ============================================================================


def test_validate_calendar_date_valid():
    assert validate_calendar_date("2026-09-10") == "2026-09-10"
    assert validate_calendar_date("2024-02-29") == "2024-02-29"  # leap year


@pytest.mark.parametrize(
    "bad_date",
    [
        "2026-02-29",  # non-leap year
        "2026-13-01",  # invalid month
        "2026-04-31",  # April has 30 days
        "2026/09/10",
        "09-10-2026",
        "invalid",
        "",
        123,
        None,
    ],
)
def test_validate_calendar_date_invalid(bad_date):
    with pytest.raises(ValueError):
        validate_calendar_date(bad_date)


def test_format_minor_units():
    assert format_minor_units(12345, 2) == "123.45"
    assert format_minor_units(-12345, 2) == "-123.45"
    assert format_minor_units(5, 2) == "0.05"
    assert format_minor_units(-5, 2) == "-0.05"
    assert format_minor_units(0, 2) == "0.00"
    assert format_minor_units(12345, 0) == "12345"
    assert format_minor_units(-12345, 0) == "-12345"
    assert format_minor_units(100_000_000, 8) == "1.00000000"


def test_format_minor_units_type_guards():
    with pytest.raises(TypeError):
        format_minor_units(True, 2)
    with pytest.raises(TypeError):
        format_minor_units(100, True)
    with pytest.raises(TypeError):
        format_minor_units(100.5, 2)
    with pytest.raises(TypeError):
        format_minor_units(100, -1)
    with pytest.raises(TypeError):
        format_minor_units(100, 19)


def test_format_beancount_price_directive_scale_4():
    # 1.2345 USD for 1 EUR (rate 12345 / 10000)
    directive = format_beancount_price_directive(
        directive_date="2026-09-10",
        base_currency="EUR",
        quote_currency="USD",
        rate_numerator=12345,
        rate_denominator=10000,
        precision_scale=4,
    )
    assert directive == "2026-09-10 price EUR 1.2345 USD"


def test_format_beancount_price_directive_bankers_rounding():
    # 5 / 2 = 2.5 -> rounds to 2 at scale 0
    dir0 = format_beancount_price_directive(
        directive_date="2026-09-10",
        base_currency="BTC",
        quote_currency="USD",
        rate_numerator=5,
        rate_denominator=2,
        precision_scale=0,
    )
    assert dir0 == "2026-09-10 price BTC 2 USD"

    # 7 / 2 = 3.5 -> rounds to 4 at scale 0
    dir1 = format_beancount_price_directive(
        directive_date="2026-09-10",
        base_currency="BTC",
        quote_currency="USD",
        rate_numerator=7,
        rate_denominator=2,
        precision_scale=0,
    )
    assert dir1 == "2026-09-10 price BTC 4 USD"


def test_format_beancount_price_directive_carry():
    # 0.99995 -> 1.0000 at scale 4 (tie rounds to 0.0000 even integer part 1)
    # 99995 / 100000 = 0.99995
    dir_carry = format_beancount_price_directive(
        directive_date="2026-09-10",
        base_currency="EUR",
        quote_currency="USD",
        rate_numerator=99995,
        rate_denominator=100000,
        precision_scale=4,
    )
    assert dir_carry == "2026-09-10 price EUR 1.0000 USD"


def test_format_beancount_price_directive_invalid_inputs():
    with pytest.raises(ValueError):
        format_beancount_price_directive("2026-02-30", "EUR", "USD", 1, 1, 4)
    with pytest.raises(ValueError):
        format_beancount_price_directive("2026-09-10", "eur", "USD", 1, 1, 4)  # lowercase currency
    with pytest.raises(ValueError):
        format_beancount_price_directive("2026-09-10", "EUR", "TOOLONG_CURRENCY", 1, 1, 4)
    with pytest.raises(TypeError):
        format_beancount_price_directive("2026-09-10", "EUR", "USD", True, 1, 4)
    with pytest.raises(TypeError):
        format_beancount_price_directive("2026-09-10", "EUR", "USD", 1, False, 4)
    with pytest.raises(TypeError):
        format_beancount_price_directive("2026-09-10", "EUR", "USD", 1, 1, -1)


# ============================================================================
# 3. ValuationEngine & Price Directive Cache Tests
# ============================================================================


def test_add_and_get_price_directive_direct(db_conn):
    engine = ValuationEngine(db_conn)
    directive = PriceDirective(
        directive_date="2026-09-01",
        base_currency="EUR",
        quote_currency="USD",
        rate_numerator=110,
        rate_denominator=100,
        precision_scale=4,
        source="MANUAL",
        ledger_id="default",
    )
    saved = engine.add_price_directive(directive)
    assert saved.id is not None
    # Check normalized gcd: 110/100 -> 11/10
    assert saved.rate_numerator == 11
    assert saved.rate_denominator == 10

    # Query as of exact date
    found = engine.get_price(
        base_currency="EUR",
        quote_currency="USD",
        as_of_date="2026-09-01",
        ledger_id="default",
    )
    assert found.rate_numerator == 11
    assert found.rate_denominator == 10
    assert found.directive_date == "2026-09-01"

    # Query as of later date resolves to the preceding directive
    found_later = engine.get_price(
        base_currency="EUR",
        quote_currency="USD",
        as_of_date="2026-09-05",
        ledger_id="default",
    )
    assert found_later.directive_date == "2026-09-01"


def test_get_price_directive_inverse_fallback(db_conn):
    engine = ValuationEngine(db_conn)
    # Record EUR -> USD @ 1.10 (11/10)
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-09-01",
            base_currency="EUR",
            quote_currency="USD",
            rate_numerator=11,
            rate_denominator=10,
            precision_scale=4,
            source="MANUAL",
            ledger_id="default",
        )
    )

    # Query USD -> EUR should invert the fraction: 10/11
    found_inverse = engine.get_price(
        base_currency="USD",
        quote_currency="EUR",
        as_of_date="2026-09-05",
        ledger_id="default",
    )
    assert found_inverse.base_currency == "USD"
    assert found_inverse.quote_currency == "EUR"
    assert found_inverse.rate_numerator == 10
    assert found_inverse.rate_denominator == 11


def test_get_price_identity_no_db(db_conn):
    engine = ValuationEngine(db_conn)
    found = engine.get_price(
        base_currency="USD",
        quote_currency="USD",
        as_of_date="2026-09-10",
        ledger_id="default",
    )
    assert found.rate_numerator == 1
    assert found.rate_denominator == 1
    assert found.base_currency == "USD"
    assert found.quote_currency == "USD"


def test_get_price_missing_raises(db_conn):
    engine = ValuationEngine(db_conn)
    with pytest.raises(MissingPriceDirectiveError):
        engine.get_price(
            base_currency="JPY",
            quote_currency="USD",
            as_of_date="2026-09-10",
            ledger_id="default",
        )


def test_get_price_stale_raises(db_conn):
    engine = ValuationEngine(db_conn)
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-08-01",
            base_currency="GBP",
            quote_currency="USD",
            rate_numerator=13,
            rate_denominator=10,
            precision_scale=4,
            source="MANUAL",
            ledger_id="default",
        )
    )
    # 40 days later, with max_staleness_days=30
    with pytest.raises(StalePriceDirectiveError):
        engine.get_price(
            base_currency="GBP",
            quote_currency="USD",
            as_of_date="2026-09-10",
            ledger_id="default",
            max_staleness_days=30,
        )


def test_engine_convert_end_to_end(db_conn):
    engine = ValuationEngine(db_conn)
    # BTC -> USD @ $60,000
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-09-01",
            base_currency="BTC",
            quote_currency="USD",
            rate_numerator=60000,
            rate_denominator=1,
            precision_scale=4,
            source="EXCHANGE_API",
            ledger_id="default",
        )
    )

    # 0.5 BTC (50,000,000 minor, scale 8) -> USD (scale 2) -> $30,000.00 (3,000,000 minor)
    converted_usd = engine.convert(
        source_minor=50_000_000,
        source_scale=8,
        base_currency="BTC",
        quote_currency="USD",
        as_of_date="2026-09-05",
        target_scale=2,
        ledger_id="default",
    )
    assert converted_usd == 3_000_000

    # Same currency conversion (identity)
    assert (
        engine.convert(
            source_minor=10000,
            source_scale=2,
            base_currency="USD",
            quote_currency="USD",
            as_of_date="2026-09-05",
            target_scale=2,
            ledger_id="default",
        )
        == 10000
    )


def test_engine_multi_tenant_isolation(db_conn):
    engine = ValuationEngine(db_conn)
    # Insert custom ledger
    db_conn.execute(
        "INSERT INTO ledgers (ledger_id, name, base_currency) VALUES ('tenant_b', 'Tenant B', 'EUR')"
    )
    db_conn.commit()

    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-09-01",
            base_currency="ETH",
            quote_currency="USD",
            rate_numerator=3000,
            rate_denominator=1,
            precision_scale=4,
            source="MANUAL",
            ledger_id="tenant_b",
        )
    )

    # Should be missing in 'default' ledger
    with pytest.raises(MissingPriceDirectiveError):
        engine.get_price(
            base_currency="ETH",
            quote_currency="USD",
            as_of_date="2026-09-05",
            ledger_id="default",
        )

    # Should be found in 'tenant_b' ledger
    found = engine.get_price(
        base_currency="ETH",
        quote_currency="USD",
        as_of_date="2026-09-05",
        ledger_id="tenant_b",
    )
    assert found.rate_numerator == 3000


def test_add_price_directive_update_existing(db_conn):
    engine = ValuationEngine(db_conn)
    # Add initial price
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-09-01",
            base_currency="EUR",
            quote_currency="USD",
            rate_numerator=110,
            rate_denominator=100,
            precision_scale=4,
            source="MANUAL",
            ledger_id="default",
        )
    )
    # Update same date & pair with new rate
    updated = engine.add_price_directive(
        PriceDirective(
            directive_date="2026-09-01",
            base_currency="EUR",
            quote_currency="USD",
            rate_numerator=115,
            rate_denominator=100,
            precision_scale=4,
            source="EXCHANGE_API",
            ledger_id="default",
        )
    )
    assert updated.rate_numerator == 23  # 115/100 reduced by gcd 5 -> 23/20
    assert updated.rate_denominator == 20
    assert updated.source == "EXCHANGE_API"


def test_ast_zero_float_division_and_no_beancount_import():
    import ast
    from pathlib import Path

    val_dir = Path(__file__).parent.parent / "src" / "ironledger" / "valuation"
    py_files = list(val_dir.glob("*.py"))
    assert len(py_files) >= 4

    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # No float division operator
            assert not isinstance(node, ast.Div), f"Found ast.Div in {py_file.name}"
            # No import beancount
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("beancount"), f"Forbidden import in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("beancount"), f"Forbidden import from {py_file.name}"


def test_reject_trailing_newline_in_currency():
    with pytest.raises(ValueError):
        PriceDirective(
            directive_date="2026-09-01",
            base_currency="USD\n",
            quote_currency="EUR",
            rate_numerator=1,
            rate_denominator=1,
        )
    with pytest.raises(ValueError):
        format_beancount_price_directive(
            directive_date="2026-09-01",
            base_currency="USD\n",
            quote_currency="EUR",
            rate_numerator=1,
            rate_denominator=1,
        )


def test_convert_identity_validates_inputs(db_conn):
    engine = ValuationEngine(db_conn)
    # Invalid date should fail even on same-currency conversion
    with pytest.raises(ValueError):
        engine.convert(
            source_minor=100,
            source_scale=2,
            base_currency="USD",
            quote_currency="USD",
            as_of_date="invalid-date",
            target_scale=2,
        )
    # Invalid scale type should fail
    with pytest.raises(TypeError):
        engine.convert(
            source_minor=100,
            source_scale=2.5,
            base_currency="USD",
            quote_currency="USD",
            as_of_date="2026-09-01",
            target_scale=2,
        )


def test_serialized_id_allocation_in_transaction(tmp_path):
    import threading
    db_file = str(tmp_path / "test_concurrent.db")
    init_conn = sqlite3.connect(db_file)
    init_conn.execute("PRAGMA journal_mode = WAL;")
    init_conn.execute("PRAGMA foreign_keys = ON;")
    migrations.migrate(init_conn)
    init_conn.close()

    errors = []
    created_ids = []

    def insert_worker(date_str: str, num: int):
        conn = sqlite3.connect(db_file, timeout=5.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        engine = ValuationEngine(conn)
        try:
            d = engine.add_price_directive(
                PriceDirective(
                    directive_date=date_str,
                    base_currency="EUR",
                    quote_currency="USD",
                    rate_numerator=num,
                    rate_denominator=1,
                )
            )
            created_ids.append(d.id)
        except Exception as e:
            errors.append(e)
        finally:
            conn.close()

    threads = [
        threading.Thread(target=insert_worker, args=(f"2026-09-0{i}", i))
        for i in range(1, 5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(created_ids) == 4
    assert len(set(created_ids)) == 4  # All IDs must be distinct
