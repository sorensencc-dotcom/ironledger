from ironledger.prices.providers.base import BasePriceProvider
from ironledger.prices.providers.manual import ManualProvider


def test_base_provider_safe_json_loads():
    data = BasePriceProvider.safe_json_loads(b'{"symbol":"AAPL","price":225.50,"volume":123}')
    assert data == {"symbol": "AAPL", "price": "225.50", "volume": "123"}


def test_manual_provider_fetch_quote():
    rec = ManualProvider({"AAPL/USD": "225.50"}).fetch_quote("AAPL", "USD")
    assert (rec.price_numerator, rec.price_denominator) == (451, 2)
    assert rec.source_provider == "manual"
