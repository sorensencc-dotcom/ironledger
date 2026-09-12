from .http import HttpPriceProvider


class CoinGeckoProvider(HttpPriceProvider):
    def __init__(self, fetcher):
        super().__init__("coingecko", fetcher)
