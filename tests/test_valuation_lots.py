from ironledger.valuation.lots import LotProcessor, InsufficientInventoryError


def seeded(strategy="FIFO"):
    p = LotProcessor(functional_currency="USD")
    p.process_acquisition("default", "Assets:Brokerage:AAPL", "AAPL", "2025-01-10", 100000, 4, 150, 1, "USD", 1, 1)
    p.process_acquisition("default", "Assets:Brokerage:AAPL", "AAPL", "2025-06-10", 100000, 4, 200, 1, "USD", 2, 2)
    return p.process_disposal("default", "Assets:Brokerage:AAPL", "AAPL", "2026-02-15", 150000, 4, 220, 1, "USD", strategy, 3, 3)


def test_fifo_partial_disposal_and_basis_conservation():
    allocations = seeded()
    assert [a.units_disposed_minor for a in allocations] == [100000, 50000]
    assert allocations[0].functional_realized_gain_minor == 70000
    assert allocations[1].functional_realized_gain_minor == 10000
    assert allocations[0].term_classification == "LONG_TERM"
    assert allocations[1].term_classification == "SHORT_TERM"


def test_lifo_and_hifo_select_second_lot_first():
    assert seeded("LIFO")[0].acquisition_date == "2025-06-10"
    assert seeded("HIFO")[0].acquisition_date == "2025-06-10"


def test_insufficient_inventory_fails_closed():
    p = LotProcessor(functional_currency="USD")
    p.process_acquisition("default", "Assets:A", "AAPL", "2025-01-01", 1, 0, 1, 1, "USD", 1, 1)
    try:
        p.process_disposal("default", "Assets:A", "AAPL", "2025-01-02", 2, 0, 1, 1, "USD", "FIFO", 2, 2)
    except InsufficientInventoryError:
        return
    raise AssertionError("expected insufficient inventory")
