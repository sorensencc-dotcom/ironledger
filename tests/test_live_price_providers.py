from __future__ import annotations

import ast
import json
from pathlib import Path
import pytest

from ironledger.prices.providers.yahoo import YahooFinanceProvider
from ironledger.prices.providers.coingecko import CoinGeckoProvider
from ironledger.prices.providers.manual import ManualProvider
from ironledger.prices.router import PriceCascadeRouter, create_default_price_router


def test_yahoo_finance_provider_mock_equity():
    mock_payload = json.dumps({
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "symbol": "NFLX",
                        "regularMarketPrice": "685.25",
                    },
                    "indicators": {"quote": [{}]},
                }
            ],
            "error": None,
        }
    })
    provider = YahooFinanceProvider(fetcher=lambda s, q: mock_payload)
    rec = provider.fetch_quote("NFLX", "USD")
    assert rec.base_currency == "NFLX"
    assert rec.quote_currency == "USD"
    assert rec.raw_quote_str == "685.25"
    assert rec.price_numerator == 2741
    assert rec.price_denominator == 4
    assert rec.source_provider == "yahoo"


def test_yahoo_finance_provider_close_fallback():
    mock_payload = json.dumps({
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "symbol": "AAPL",
                        "regularMarketPrice": None,
                    },
                    "indicators": {
                        "quote": [{"close": [None, "225.50"]}]
                    },
                }
            ],
            "error": None,
        }
    })
    provider = YahooFinanceProvider(fetcher=lambda s, q: mock_payload)
    rec = provider.fetch_quote("AAPL", "USD")
    assert rec.raw_quote_str == "225.50"
    assert rec.price_numerator == 451
    assert rec.price_denominator == 2


def test_yahoo_finance_provider_error_handling():
    error_payload = json.dumps({
        "chart": {
            "result": None,
            "error": {"code": "Not Found", "description": "No data found for symbol XYZ"},
        }
    })
    provider = YahooFinanceProvider(fetcher=lambda s, q: error_payload)
    with pytest.raises(ValueError, match="Yahoo error for XYZ"):
        provider.fetch_quote("XYZ", "USD")


def test_coingecko_provider_mock_crypto():
    mock_payload = json.dumps({
        "bitcoin": {
            "usd": "61250.75"
        }
    })
    provider = CoinGeckoProvider(fetcher=lambda s, q: mock_payload)
    rec = provider.fetch_quote("BTC", "USD")
    assert rec.base_currency == "BTC"
    assert rec.quote_currency == "USD"
    assert rec.raw_quote_str == "61250.75"
    assert rec.price_numerator == 245003
    assert rec.price_denominator == 4
    assert rec.source_provider == "coingecko"


def test_coingecko_provider_ethereum():
    mock_payload = json.dumps({
        "ethereum": {
            "usd": "2420.50"
        }
    })
    provider = CoinGeckoProvider(fetcher=lambda s, q: mock_payload)
    rec = provider.fetch_quote("ETH", "USD")
    assert rec.base_currency == "ETH"
    assert rec.raw_quote_str == "2420.50"
    assert rec.price_numerator == 4841
    assert rec.price_denominator == 2


def test_coingecko_provider_missing_symbol():
    mock_payload = json.dumps({})
    provider = CoinGeckoProvider(fetcher=lambda s, q: mock_payload)
    with pytest.raises(ValueError, match="No CoinGecko price found"):
        provider.fetch_quote("UNKNOWNCOIN", "USD")


def test_cascade_router_failover_to_manual():
    def failing_fetcher(s, q):
        raise RuntimeError("Network unreachable")

    yahoo = YahooFinanceProvider(fetcher=failing_fetcher)
    coingecko = CoinGeckoProvider(fetcher=failing_fetcher)
    manual = ManualProvider(static_quotes={"NFLX/USD": "700.00"})

    router = PriceCascadeRouter({"DEFAULT": [yahoo, coingecko, manual]})
    rec = router.resolve_quote("NFLX", "USD")
    assert rec.base_currency == "NFLX"
    assert rec.raw_quote_str == "700.00"
    assert rec.price_numerator == 700
    assert rec.price_denominator == 1
    assert rec.source_provider == "manual"


def test_create_default_price_router_initialization():
    router = create_default_price_router(manual_quotes={"AAPL/USD": "225.50"})
    chain = router.provider_chains.get("DEFAULT", [])
    assert len(chain) == 3
    assert chain[0].provider_id == "yahoo"
    assert chain[1].provider_id == "coingecko"
    assert chain[2].provider_id == "manual"


def test_ast_zero_float_division_in_prices_module():
    """Ensure no float division (ast.Div) exists in any ironledger.prices module."""
    prices_dir = Path(__file__).resolve().parent.parent.joinpath("src", "ironledger", "prices")
    for py_file in prices_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Div), (
                f"Float division operator '/' (ast.Div) forbidden in {py_file}:{getattr(node, 'lineno', '?')}"
            )
