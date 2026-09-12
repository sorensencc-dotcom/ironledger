import ast
import inspect

import pytest

from ironledger.prices import models
from ironledger.prices.models import PriceDirectiveRecord


def test_price_directive_from_decimal_str():
    rec = PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "225.50", "yahoo")
    assert (rec.price_numerator, rec.price_denominator) == (451, 2)
    assert rec.source_provider == "yahoo"


def test_price_directive_reciprocal():
    rec = PriceDirectiveRecord.from_decimal_str("2026-09-12", "EUR", "USD", "1.10", "yahoo")
    inv = rec.reciprocal()
    assert (inv.base_currency, inv.quote_currency) == ("USD", "EUR")
    assert (inv.price_numerator, inv.price_denominator) == (10, 11)


def test_price_directive_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="Scientific notation"):
        PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "1e5", "yahoo")
    with pytest.raises(ValueError, match="positive and finite"):
        PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "-10.5", "yahoo")
    with pytest.raises(ValueError, match="positive and finite"):
        PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "NaN", "yahoo")


def test_beancount_directive_is_plain_decimal():
    rec = PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "225.50", "manual")
    assert rec.to_beancount_directive() == "2026-09-12 price AAPL       225.5000 USD"


def test_ast_zero_float_scan():
    tree = ast.parse(inspect.getsource(models))
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in {"float", "float64", "float32"}]
