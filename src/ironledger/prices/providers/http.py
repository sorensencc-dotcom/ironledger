from __future__ import annotations

from collections.abc import Callable

from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.base import BasePriceProvider


class HttpPriceProvider(BasePriceProvider):
    def __init__(self, provider_id, fetcher: Callable[[str, str], str], price_key="price"):
        super().__init__(provider_id)
        self.fetcher = fetcher
        self.price_key = price_key

    def fetch_quote(self, symbol, quote_currency):
        self._acquire()
        data = self.safe_json_loads(self.fetcher(symbol, quote_currency))
        raw = data[self.price_key]
        return PriceDirectiveRecord.from_decimal_str(
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d"),
            symbol, quote_currency, raw, self.provider_id,
        )
