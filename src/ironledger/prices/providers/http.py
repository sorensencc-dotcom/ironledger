from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.base import BasePriceProvider


class HttpPriceProvider(BasePriceProvider):
    def __init__(
        self,
        provider_id: str,
        fetcher: Callable[[str, str], str],
        price_key: str = "price",
        extractor: Callable[[Any, str, str], str] | None = None,
        rate_limit_rpm: int = 60,
        burst_capacity: int = 10,
    ):
        super().__init__(provider_id, rate_limit_rpm=rate_limit_rpm, burst_capacity=burst_capacity)
        self.fetcher = fetcher
        self.price_key = price_key
        self.extractor = extractor

    def fetch_quote(self, symbol: str, quote_currency: str) -> PriceDirectiveRecord:
        self._acquire()
        data = self.safe_json_loads(self.fetcher(symbol, quote_currency))
        if self.extractor is not None:
            raw = self.extractor(data, symbol, quote_currency)
        else:
            raw = str(data[self.price_key])
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        return PriceDirectiveRecord.from_decimal_str(
            today,
            symbol,
            quote_currency,
            str(raw),
            self.provider_id,
        )

