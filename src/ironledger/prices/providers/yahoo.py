from __future__ import annotations

import urllib.request
import urllib.parse
from collections.abc import Callable
from typing import Any

from .http import HttpPriceProvider


def _default_yahoo_fetcher(symbol: str, quote_currency: str) -> str:
    sym = symbol.upper()
    quote = quote_currency.upper()
    if sym in ("EUR", "GBP", "JPY", "CAD", "AUD", "CHF"):
        ticker = f"{sym}{quote}=X"
    elif sym in ("BTC", "ETH", "SOL", "DOGE"):
        ticker = f"{sym}-{quote}"
    else:
        ticker = sym

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=1d"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return resp.read().decode("utf-8")


def _extract_yahoo_price(data: Any, symbol: str, quote_currency: str) -> str:
    try:
        results = data.get("chart", {}).get("result")
        if not results:
            error = data.get("chart", {}).get("error", {})
            raise ValueError(f"Yahoo error for {symbol}: {error.get('description', 'No result found')}")
        meta = results[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is not None and str(price).strip() != "":
            return str(price)
        quotes = results[0].get("indicators", {}).get("quote", [])
        if quotes and quotes[0].get("close"):
            closes = [c for c in quotes[0]["close"] if c is not None]
            if closes:
                return str(closes[-1])
        raise ValueError(f"No valid price in Yahoo response for {symbol}")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Malformed Yahoo response for {symbol}") from exc


class YahooFinanceProvider(HttpPriceProvider):
    def __init__(self, fetcher: Callable[[str, str], str] | None = None, rate_limit_rpm: int = 60):
        super().__init__(
            provider_id="yahoo",
            fetcher=fetcher or _default_yahoo_fetcher,
            extractor=_extract_yahoo_price,
            rate_limit_rpm=rate_limit_rpm,
            burst_capacity=10,
        )

