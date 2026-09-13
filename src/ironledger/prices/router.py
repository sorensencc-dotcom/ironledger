from __future__ import annotations

import logging

from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.base import BasePriceProvider

logger = logging.getLogger(__name__)


class PriceCascadeRouter:
    def __init__(self, provider_chains: dict[str, list[BasePriceProvider]]):
        self.provider_chains = provider_chains

    def resolve_quote(self, symbol, quote_currency="USD", chain_key="DEFAULT") -> PriceDirectiveRecord:
        chain = self.provider_chains.get(chain_key) or self.provider_chains.get("DEFAULT", [])
        if not chain:
            raise RuntimeError(f"No configured price providers for chain key: {chain_key}")
        last_error = None
        for provider in chain:
            try:
                return provider.circuit_breaker.execute(provider.fetch_quote, symbol=symbol, quote_currency=quote_currency)
            except Exception as exc:
                last_error = exc
                logger.warning("Provider %s failed for %s/%s: %s", provider.provider_id, symbol, quote_currency, exc)
        for provider in chain:
            try:
                inverse = provider.circuit_breaker.execute(provider.fetch_quote, symbol=quote_currency, quote_currency=symbol)
                return inverse.reciprocal(source_provider=f"{provider.provider_id}_reciprocal")
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"All providers in cascade failed for {symbol}/{quote_currency}") from last_error


def create_default_price_router(manual_quotes: dict[str, str] | None = None) -> PriceCascadeRouter:
    from ironledger.prices.providers.coingecko import CoinGeckoProvider
    from ironledger.prices.providers.manual import ManualProvider
    from ironledger.prices.providers.yahoo import YahooFinanceProvider

    providers: list[BasePriceProvider] = [
        YahooFinanceProvider(),
        CoinGeckoProvider(),
        ManualProvider(static_quotes=manual_quotes or {}),
    ]
    return PriceCascadeRouter({"DEFAULT": providers})

