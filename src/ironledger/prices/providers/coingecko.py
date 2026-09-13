from __future__ import annotations

import urllib.request
import urllib.parse
from collections.abc import Callable
from typing import Any

from .http import HttpPriceProvider

COINGECKO_ID_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
}


def _default_coingecko_fetcher(symbol: str, quote_currency: str) -> str:
    sym = symbol.upper()
    coin_id = COINGECKO_ID_MAP.get(sym, sym.lower())
    vs = quote_currency.lower()
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={urllib.parse.quote(coin_id)}&vs_currencies={urllib.parse.quote(vs)}"
    headers = {
        "User-Agent": "IronLedger/1.0 (Price-Feed-Scraper)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return resp.read().decode("utf-8")


def _extract_coingecko_price(data: Any, symbol: str, quote_currency: str) -> str:
    sym = symbol.upper()
    coin_id = COINGECKO_ID_MAP.get(sym, sym.lower())
    vs = quote_currency.lower()
    try:
        coin_data = data.get(coin_id)
        if not coin_data or vs not in coin_data:
            raise ValueError(f"No CoinGecko price found for {symbol} ({coin_id}) in {quote_currency}")
        price = coin_data[vs]
        if price is None or str(price).strip() == "":
            raise ValueError(f"Empty CoinGecko price for {symbol}")
        return str(price)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Malformed CoinGecko response for {symbol}") from exc


class CoinGeckoProvider(HttpPriceProvider):
    def __init__(self, fetcher: Callable[[str, str], str] | None = None, rate_limit_rpm: int = 30):
        super().__init__(
            provider_id="coingecko",
            fetcher=fetcher or _default_coingecko_fetcher,
            extractor=_extract_coingecko_price,
            rate_limit_rpm=rate_limit_rpm,
            burst_capacity=5,
        )

