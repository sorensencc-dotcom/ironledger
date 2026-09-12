from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.manual import ManualProvider
from ironledger.prices.router import PriceCascadeRouter


class FailingProvider(ManualProvider):
    def __init__(self):
        super().__init__()
        self.provider_id = "primary"

    def fetch_quote(self, symbol, quote_currency):
        raise ConnectionError("outage")


def test_router_cascade_failover():
    rec = PriceCascadeRouter({"DEFAULT": [FailingProvider(), ManualProvider({"AAPL/USD": "225.50"})]}).resolve_quote("AAPL", "USD")
    assert rec.source_provider == "manual"
    assert rec.price_numerator == 451


def test_router_reciprocal_resolution():
    rec = PriceCascadeRouter({"DEFAULT": [ManualProvider({"EUR/USD": "1.25"})]}).resolve_quote("USD", "EUR")
    assert (rec.base_currency, rec.quote_currency) == ("USD", "EUR")
    assert (rec.price_numerator, rec.price_denominator) == (4, 5)


def test_router_fails_closed_when_chain_empty():
    try:
        PriceCascadeRouter({}).resolve_quote("AAPL", "USD")
    except RuntimeError as exc:
        assert "No configured" in str(exc)
    else:
        raise AssertionError("router unexpectedly resolved with no providers")
