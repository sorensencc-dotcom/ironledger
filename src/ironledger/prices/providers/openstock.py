from .http import HttpPriceProvider


class OpenStockScraperProvider(HttpPriceProvider):
    def __init__(self, fetcher):
        super().__init__("openstock", fetcher)
