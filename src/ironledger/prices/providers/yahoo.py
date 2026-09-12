from .http import HttpPriceProvider


class YahooFinanceProvider(HttpPriceProvider):
    def __init__(self, fetcher):
        super().__init__("yahoo", fetcher)
