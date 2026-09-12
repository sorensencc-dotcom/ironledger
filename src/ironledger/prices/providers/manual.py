from __future__ import annotations

import datetime

from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.base import BasePriceProvider


class ManualProvider(BasePriceProvider):
    def __init__(self, static_quotes=None):
        super().__init__("manual", rate_limit_rpm=1000, burst_capacity=100)
        self.quotes = static_quotes or {}

    def fetch_quote(self, symbol, quote_currency):
        self._acquire()
        key = f"{symbol.upper()}/{quote_currency.upper()}"
        if key not in self.quotes:
            raise KeyError(f"No manual quote registered for {key}")
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        return PriceDirectiveRecord.from_decimal_str(today, symbol, quote_currency, self.quotes[key], self.provider_id)
