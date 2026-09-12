from __future__ import annotations

import abc
import json
from typing import Any

from ironledger.connectors.circuit_breaker import CircuitBreaker
from ironledger.connectors.rate_limiter import TokenBucketRateLimiter
from ironledger.prices.models import PriceDirectiveRecord


class BasePriceProvider(abc.ABC):
    def __init__(self, provider_id, rate_limit_rpm=60, burst_capacity=10, circuit_breaker=None):
        self.provider_id = provider_id
        self.rate_limiter = TokenBucketRateLimiter(rate_limit_rpm, burst_capacity)
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    @staticmethod
    def safe_json_loads(raw_bytes_or_str: str | bytes) -> Any:
        return json.loads(raw_bytes_or_str, parse_float=str, parse_int=str)

    def _acquire(self) -> None:
        if not self.rate_limiter.acquire():
            raise RuntimeError(f"Rate limit exhausted for provider {self.provider_id}")

    @abc.abstractmethod
    def fetch_quote(self, symbol: str, quote_currency: str) -> PriceDirectiveRecord:
        raise NotImplementedError
