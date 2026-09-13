import pytest

from ironledger.valuation.models import parse_lot_annotation


def test_parse_per_unit_cost():
    ann = parse_lot_annotation(
        '{150.50 USD, 2026-05-01, "lot-1"}', unit_scale=4, posting_units_minor=100000
    )
    assert ann.native_cost_numerator == 301
    assert ann.native_cost_denominator == 2
    assert ann.native_cost_currency == "USD"
    assert ann.lot_date == "2026-05-01"
    assert ann.lot_label == "lot-1"


def test_parse_total_cost_normalization():
    ann = parse_lot_annotation("{{1500.00 USD}}", unit_scale=4, posting_units_minor=100000)
    assert ann.native_cost_numerator == 150
    assert ann.native_cost_denominator == 1
    assert ann.is_total_cost is True


def test_zero_units_rejected_for_total_cost():
    with pytest.raises(ValueError):
        parse_lot_annotation("{{1500.00 USD}}", unit_scale=4, posting_units_minor=0)
