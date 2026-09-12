# Governed Multi-Provider Commodity Price Feed Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a governed, zero-float, multi-provider commodity and currency price feed daemon that continuously resolves market quotes across fallback feeds, writes to plain-text `prices.beancount` under file locks, updates SQLite `price_history` projections, and exposes FastMCP / CLI controls.

**Architecture:** A decoupled `BasePriceProvider` hierarchy wrapping `TokenBucketRateLimiter` and `CircuitBreaker` instances; a `PriceCascadeRouter` managing deterministic fallbacks, reciprocal $(D/N)$ fraction inversions, and UTC staleness gating; a `PriceScraperDaemon` performing portfolio discovery and atomic dual persistence; and schema migration `0017_price_feed_audit.sql`.

**Tech Stack:** Python 3.12+, SQLite 3.45+ (WAL mode STRICT tables), Beancount AST syntax, FastMCP tools protocol, pytest.

## Global Constraints

- Zero-float arithmetic: `float` and `numpy` are strictly forbidden; all prices must be exact integer rationals $(N/D)$.
- Network JSON decoding: All upstream network JSON responses must use `parse_float=str` to prevent floating-point ingress.
- Plain-text ground truth: `ledger/prices.beancount` is the source of truth, written with exclusive file locks and `os.fsync()`.
- Maximum staleness: Fallback terminates at a hard 7-day ($604,800\text{s}$) UTC boundary before failing closed.
- 64-bit integer limits: Rational numerators and denominators must satisfy $1 \le N, D \le 9{,}223{,}372{,}036{,}854{,}775{,}807$.

---

### Task 1: Schema Migration `0017_price_feed_audit.sql`

**Files:**
- Create: `src/ironledger/db/schema/0017_price_feed_audit.sql`
- Test: `tests/test_migration_0017.py`

**Interfaces:**
- Consumes: `ironledger.db.migrations.migrate`
- Produces: `price_feed_audit` table with columns `(audit_id, ledger_id, symbol, quote_currency, provider_id, status, rate_numerator, rate_denominator, latency_ms, error_message, created_at)`

- [ ] **Step 1: Write failing test for migration 0017**

```python
# tests/test_migration_0017.py
import sqlite3
from ironledger.db import migrations
from ironledger.db.connection import connect


def test_migration_0017_creates_price_feed_audit_table(tmp_path):
    db_path = tmp_path / "test_migration_0017.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)

    # Verify table schema
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_feed_audit'")
    assert cursor.fetchone() is not None

    # Verify columns and check constraints
    cursor.execute(
        """
        INSERT INTO price_feed_audit (
            ledger_id, symbol, quote_currency, provider_id, status,
            rate_numerator, rate_denominator, latency_ms, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("default", "AAPL", "USD", "yahoo", "SUCCESS", 22550, 100, 142, None),
    )
    conn.commit()

    cursor.execute("SELECT symbol, quote_currency, rate_numerator, rate_denominator FROM price_feed_audit WHERE symbol='AAPL'")
    row = cursor.fetchone()
    assert row == ("AAPL", "USD", 22550, 100)
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_0017.py -v`
Expected: FAIL with `AssertionError: assert None is not None` or table missing.

- [ ] **Step 3: Write migration SQL file**

```sql
-- src/ironledger/db/schema/0017_price_feed_audit.sql
-- Migration 0017: Price Feed Outbound Resolution Audit Log

CREATE TABLE IF NOT EXISTS price_feed_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL CHECK (length(symbol) >= 1 AND length(symbol) <= 24),
    quote_currency TEXT NOT NULL CHECK (length(quote_currency) >= 3 AND length(quote_currency) <= 8),
    provider_id TEXT NOT NULL CHECK (length(provider_id) >= 1 AND length(provider_id) <= 64),
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FALLTHROUGH_FAIL', 'CIRCUIT_OPEN', 'STALE_CACHED', 'RECIPROCAL_SUCCESS')),
    rate_numerator INTEGER CHECK (rate_numerator IS NULL OR rate_numerator > 0),
    rate_denominator INTEGER CHECK (rate_denominator IS NULL OR rate_denominator > 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_price_feed_audit_symbol 
ON price_feed_audit (ledger_id, symbol, quote_currency, created_at DESC);
```

- [ ] **Step 4: Run migration test to verify it passes**

Run: `pytest tests/test_migration_0017.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/db/schema/0017_price_feed_audit.sql tests/test_migration_0017.py
git commit -m "feat(schema): add migration 0017 for price feed audit log"
```

---

### Task 2: Data Models, GCD Rational Arithmetic & AST Zero-Float Scan

**Files:**
- Create: `src/ironledger/prices/__init__.py`
- Create: `src/ironledger/prices/models.py`
- Create: `tests/test_price_models.py`

**Interfaces:**
- Produces: `PriceDirectiveRecord`, `PriceDirectiveRecord.from_decimal_str`, `PriceDirectiveRecord.reciprocal`, `PriceDirectiveRecord.to_beancount_directive`

- [ ] **Step 1: Write failing tests for PriceDirectiveRecord**

```python
# tests/test_price_models.py
import ast
import inspect
import pytest
from ironledger.prices import models
from ironledger.prices.models import PriceDirectiveRecord


def test_price_directive_from_decimal_str():
    rec = PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "225.50", "yahoo")
    assert rec.directive_date == "2026-09-12"
    assert rec.base_currency == "AAPL"
    assert rec.quote_currency == "USD"
    # Canonicalized with GCD: 22550/100 -> 451/2
    assert rec.price_numerator == 451
    assert rec.price_denominator == 2
    assert type(rec.price_numerator) is int
    assert type(rec.price_denominator) is int
    assert rec.source_provider == "yahoo"


def test_price_directive_reciprocal():
    rec = PriceDirectiveRecord.from_decimal_str("2026-09-12", "EUR", "USD", "1.10", "yahoo")
    # 1.10 -> 11/10
    assert (rec.price_numerator, rec.price_denominator) == (11, 10)

    inv = rec.reciprocal()
    assert inv.base_currency == "USD"
    assert inv.quote_currency == "EUR"
    assert (inv.price_numerator, inv.price_denominator) == (10, 11)


def test_price_directive_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="Scientific notation"):
        PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "1e5", "yahoo")

    with pytest.raises(ValueError, match="positive and finite"):
        PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "-10.5", "yahoo")

    with pytest.raises(ValueError, match="positive and finite"):
        PriceDirectiveRecord.from_decimal_str("2026-09-12", "AAPL", "USD", "NaN", "yahoo")


def test_ast_zero_float_scan():
    tree = ast.parse(inspect.getsource(models))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ("float", "float64", "float32"):
            pytest.fail(f"Zero-float violation: found reference to '{node.id}' in models.py line {node.lineno}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.prices'`

- [ ] **Step 3: Implement `src/ironledger/prices/models.py`**

```python
# src/ironledger/prices/__init__.py
"""Governed multi-provider commodity price feed module."""

# src/ironledger/prices/models.py
from __future__ import annotations
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

TICKER_PATTERN = re.compile(r"^[A-Z0-9._-]{1,24}$")
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3,8}$")
MAX_SQLITE_INT = 9_223_372_036_854_775_807  # 2^63 - 1


@dataclass(frozen=True)
class PriceDirectiveRecord:
    directive_date: str          # YYYY-MM-DD
    base_currency: str           # Commodity / Ticker
    quote_currency: str          # Pricing currency (e.g. USD)
    price_numerator: int         # Exact integer numerator (canonicalized)
    price_denominator: int       # Exact integer denominator (canonicalized)
    source_provider: str         # e.g. "yahoo", "openstock", "coingecko"
    raw_quote_str: str           # Original raw decimal string

    def __post_init__(self) -> None:
        if not TICKER_PATTERN.match(self.base_currency):
            raise ValueError(f"Invalid base commodity: {self.base_currency!r}")
        if not CURRENCY_PATTERN.match(self.quote_currency):
            raise ValueError(f"Invalid quote currency: {self.quote_currency!r}")
        if type(self.price_numerator) is not int or self.price_numerator <= 0:
            raise ValueError("Price numerator must be a positive integer")
        if type(self.price_denominator) is not int or self.price_denominator <= 0:
            raise ValueError("Price denominator must be a positive integer")
        if self.price_numerator > MAX_SQLITE_INT or self.price_denominator > MAX_SQLITE_INT:
            raise OverflowError("Price rational exceeds 64-bit integer range")

    @classmethod
    def from_decimal_str(
        cls,
        directive_date: str,
        base_currency: str,
        quote_currency: str,
        raw_price: str,
        source_provider: str,
    ) -> PriceDirectiveRecord:
        """Parses raw ASCII decimal string directly into a GCD-reduced integer rational."""
        if not isinstance(raw_price, str):
            raise TypeError(f"raw_price must be a string, got {type(raw_price).__name__}")
        
        cleaned = raw_price.strip().replace(",", "")
        if "e" in cleaned.lower():
            raise ValueError("Scientific notation is forbidden in price quotes")

        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"Malformed price string: {raw_price!r}") from exc

        if not dec.is_finite() or dec <= 0:
            raise ValueError(f"Price quote must be positive and finite: {raw_price!r}")

        sign, digits, exponent = dec.as_tuple()
        if exponent < -18 or exponent > 0:
            raise ValueError(f"Decimal exponent {exponent} out of allowed range [-18, 0]")

        raw_num = int("".join(map(str, digits)))
        raw_denom = 10 ** abs(exponent)

        # Canonicalize with Greatest Common Divisor
        common = math.gcd(raw_num, raw_denom)
        numerator = raw_num // common
        denominator = raw_denom // common

        return cls(
            directive_date=directive_date,
            base_currency=base_currency.upper(),
            quote_currency=quote_currency.upper(),
            price_numerator=numerator,
            price_denominator=denominator,
            source_provider=source_provider,
            raw_quote_str=cleaned,
        )

    def reciprocal(self, source_provider: str = "reciprocal") -> PriceDirectiveRecord:
        """Returns exact inverted rate (D/N) with zero floating-point arithmetic."""
        return PriceDirectiveRecord(
            directive_date=self.directive_date,
            base_currency=self.quote_currency,
            quote_currency=self.base_currency,
            price_numerator=self.price_denominator,
            price_denominator=self.price_numerator,
            source_provider=source_provider,
            raw_quote_str=f"{self.price_denominator}/{self.price_numerator}",
        )

    def to_beancount_directive(self) -> str:
        """Emits canonical Beancount price directive with pinned 4-decimal precision."""
        val = Decimal(self.price_numerator) / Decimal(self.price_denominator)
        return f"{self.directive_date} price {self.base_currency:<10} {val:.4f} {self.quote_currency}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_price_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/prices/ models.py tests/test_price_models.py
git commit -m "feat(prices): add PriceDirectiveRecord with zero-float GCD arithmetic"
```

---

### Task 3: Decoupled Provider Adapters & JSON Ingress Defense

**Files:**
- Create: `src/ironledger/prices/providers/__init__.py`
- Create: `src/ironledger/prices/providers/base.py`
- Create: `src/ironledger/prices/providers/yahoo.py`
- Create: `src/ironledger/prices/providers/openstock.py`
- Create: `src/ironledger/prices/providers/coingecko.py`
- Create: `src/ironledger/prices/providers/manual.py`
- Test: `tests/test_price_providers.py`

**Interfaces:**
- Produces: `BasePriceProvider`, `YahooFinanceProvider`, `OpenStockScraperProvider`, `CoinGeckoProvider`, `ManualProvider`

- [ ] **Step 1: Write failing test for providers and safe JSON parsing**

```python
# tests/test_price_providers.py
import pytest
from ironledger.prices.providers.base import BasePriceProvider
from ironledger.prices.providers.manual import ManualProvider
from ironledger.prices.models import PriceDirectiveRecord


def test_base_provider_safe_json_loads():
    json_bytes = b'{"symbol": "AAPL", "price": 225.50, "volume": 1234567}'
    data = BasePriceProvider.safe_json_loads(json_bytes)
    # Price must be parsed as str, never float
    assert isinstance(data["price"], str)
    assert data["price"] == "225.50"


def test_manual_provider_fetch_quote():
    provider = ManualProvider({"AAPL/USD": "225.50"})
    rec = provider.fetch_quote("AAPL", "USD")
    assert rec.base_currency == "AAPL"
    assert rec.quote_currency == "USD"
    assert rec.price_numerator == 451
    assert rec.price_denominator == 2
    assert rec.source_provider == "manual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.prices.providers'`

- [ ] **Step 3: Implement provider classes**

```python
# src/ironledger/prices/providers/__init__.py
"""Price provider adapters."""

# src/ironledger/prices/providers/base.py
from __future__ import annotations
import abc
import json
from typing import Any
from ironledger.connectors.circuit_breaker import CircuitBreaker
from ironledger.connectors.rate_limiter import TokenBucketRateLimiter
from ironledger.prices.models import PriceDirectiveRecord


class BasePriceProvider(abc.ABC):
    """Dedicated abstract base for rate-limited, circuit-broken price providers."""

    def __init__(
        self,
        provider_id: str,
        rate_limit_rpm: int = 60,
        burst_capacity: int = 10,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self.provider_id = provider_id
        self.rate_limiter = TokenBucketRateLimiter(rate_limit_rpm, burst_capacity)
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    @staticmethod
    def safe_json_loads(raw_bytes_or_str: str | bytes) -> Any:
        """Decodes JSON ensuring all numbers parse strictly as string objects, not floats."""
        return json.loads(raw_bytes_or_str, parse_float=str, parse_int=str)

    @abc.abstractmethod
    def fetch_quote(self, symbol: str, quote_currency: str) -> PriceDirectiveRecord:
        """Fetches quote and returns verified PriceDirectiveRecord."""


# src/ironledger/prices/providers/manual.py
from __future__ import annotations
import datetime
from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.base import BasePriceProvider


class ManualProvider(BasePriceProvider):
    def __init__(self, static_quotes: dict[str, str] | None = None):
        super().__init__(provider_id="manual", rate_limit_rpm=1000, burst_capacity=100)
        self.quotes = static_quotes or {}

    def fetch_quote(self, symbol: str, quote_currency: str) -> PriceDirectiveRecord:
        key = f"{symbol.upper()}/{quote_currency.upper()}"
        if key not in self.quotes:
            raise KeyError(f"No manual quote registered for {key}")
        price_str = self.quotes[key]
        today_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        return PriceDirectiveRecord.from_decimal_str(
            directive_date=today_utc,
            base_currency=symbol,
            quote_currency=quote_currency,
            raw_price=price_str,
            source_provider="manual",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_price_providers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/prices/providers/ tests/test_price_providers.py
git commit -m "feat(prices): add BasePriceProvider and ManualProvider with safe JSON ingress"
```

---

### Task 4: Priority Cascade Router, Reciprocal Rates & Staleness Gating

**Files:**
- Create: `src/ironledger/prices/router.py`
- Test: `tests/test_price_router.py`

**Interfaces:**
- Consumes: `BasePriceProvider`, `PriceDirectiveRecord`
- Produces: `PriceCascadeRouter`, `PriceCascadeRouter.resolve_quote`

- [ ] **Step 1: Write failing test for cascade router and circuit breaker failover**

```python
# tests/test_price_router.py
import pytest
from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.manual import ManualProvider
from ironledger.prices.router import PriceCascadeRouter


class FailingProvider(ManualProvider):
    def __init__(self, provider_id="failing"):
        super().__init__()
        self.provider_id = provider_id

    def fetch_quote(self, symbol: str, quote_currency: str) -> PriceDirectiveRecord:
        raise ConnectionError("Simulated provider outage / HTTP 429")


def test_router_cascade_failover():
    p1 = FailingProvider("primary")
    p2 = ManualProvider({"AAPL/USD": "225.50"})
    
    router = PriceCascadeRouter(provider_chains={"DEFAULT": [p1, p2]})
    rec = router.resolve_quote("AAPL", "USD")
    
    assert rec.base_currency == "AAPL"
    assert rec.source_provider == "manual"
    assert rec.price_numerator == 451


def test_router_reciprocal_resolution():
    # Only EUR/USD is configured; request USD/EUR
    p = ManualProvider({"EUR/USD": "1.25"})
    router = PriceCascadeRouter(provider_chains={"DEFAULT": [p]})

    rec = router.resolve_quote("USD", "EUR")
    assert rec.base_currency == "USD"
    assert rec.quote_currency == "EUR"
    # 1.25 -> 5/4. Reciprocal -> 4/5
    assert (rec.price_numerator, rec.price_denominator) == (4, 5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.prices.router'`

- [ ] **Step 3: Implement `src/ironledger/prices/router.py`**

```python
# src/ironledger/prices/router.py
from __future__ import annotations
import logging
from typing import Dict, List, Optional
from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.base import BasePriceProvider

logger = logging.getLogger("ironledger.prices.router")


class PriceCascadeRouter:
    """Dispatches quote lookups through an ordered sequence of fallback providers."""

    def __init__(self, provider_chains: Dict[str, List[BasePriceProvider]]):
        self.provider_chains = provider_chains

    def resolve_quote(
        self,
        symbol: str,
        quote_currency: str = "USD",
        chain_key: str = "DEFAULT",
    ) -> PriceDirectiveRecord:
        chain = self.provider_chains.get(chain_key) or self.provider_chains.get("DEFAULT", [])
        if not chain:
            raise RuntimeError(f"No configured price providers for chain key: {chain_key}")

        last_error: Optional[Exception] = None

        # 1. Try direct quote lookup
        for provider in chain:
            try:
                record = provider.circuit_breaker.execute(
                    provider.fetch_quote,
                    symbol=symbol,
                    quote_currency=quote_currency,
                )
                logger.info(
                    "Resolved %s/%s via provider %s (%s)",
                    symbol, quote_currency, provider.provider_id, record.raw_quote_str
                )
                return record
            except Exception as err:
                logger.warning(
                    "Provider %s failed for %s/%s: %s. Falling back...",
                    provider.provider_id, symbol, quote_currency, err
                )
                last_error = err

        # 2. Try reciprocal quote lookup (QUOTE / BASE)
        for provider in chain:
            try:
                inv_record = provider.circuit_breaker.execute(
                    provider.fetch_quote,
                    symbol=quote_currency,
                    quote_currency=symbol,
                )
                rec = inv_record.reciprocal(source_provider=f"{provider.provider_id}_reciprocal")
                logger.info(
                    "Resolved reciprocal %s/%s via provider %s",
                    symbol, quote_currency, provider.provider_id
                )
                return rec
            except Exception:
                pass

        raise RuntimeError(
            f"All providers in cascade failed for {symbol}/{quote_currency}. Last error: {last_error}"
        ) from last_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_price_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/prices/router.py tests/test_price_router.py
git commit -m "feat(prices): add PriceCascadeRouter with fallback failover and reciprocal math"
```

---

### Task 5: Scraper Daemon, File Locking & Dual Beancount/SQLite Sync

**Files:**
- Create: `src/ironledger/prices/scraper_daemon.py`
- Test: `tests/test_price_scraper.py`

**Interfaces:**
- Consumes: `PriceCascadeRouter`, `PriceDirectiveRecord`
- Produces: `PriceScraperDaemon`, `PriceScraperDaemon.sync_watchlist`

- [ ] **Step 1: Write failing test for PriceScraperDaemon**

```python
# tests/test_price_scraper.py
from pathlib import Path
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.providers.manual import ManualProvider
from ironledger.prices.router import PriceCascadeRouter
from ironledger.prices.scraper_daemon import PriceScraperDaemon


def test_scraper_daemon_sync_watchlist(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.close()

    prices_path = tmp_path / "ledger" / "prices.beancount"
    provider = ManualProvider({"AAPL/USD": "225.50", "MSFT/USD": "420.00"})
    router = PriceCascadeRouter(provider_chains={"DEFAULT": [provider]})

    daemon = PriceScraperDaemon(
        db_path=db_path,
        prices_ledger_path=prices_path,
        router=router,
        ledger_id="default",
    )

    res = daemon.sync_watchlist([("AAPL", "USD"), ("MSFT", "USD")])
    assert res["status"] == "success"
    assert res["synced_count"] == 2

    # Verify plain-text file exists and contains directives
    content = prices_path.read_text(encoding="utf-8")
    assert "price AAPL" in content
    assert "price MSFT" in content

    # Verify SQLite price_history rows updated
    conn = connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT base_currency, quote_currency, rate_numerator, rate_denominator FROM price_history ORDER BY base_currency")
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "AAPL"
    assert rows[1][0] == "MSFT"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_scraper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ironledger.prices.scraper_daemon'`

- [ ] **Step 3: Implement `src/ironledger/prices/scraper_daemon.py`**

```python
# src/ironledger/prices/scraper_daemon.py
from __future__ import annotations
import datetime
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple
from ironledger.prices.models import PriceDirectiveRecord
from ironledger.prices.router import PriceCascadeRouter


class PriceScraperDaemon:
    """Orchestrates watchlist polling, atomic Beancount appending, and SQLite synchronization."""

    def __init__(
        self,
        db_path: Path,
        prices_ledger_path: Path,
        router: PriceCascadeRouter,
        ledger_id: str = "default",
    ):
        self.db_path = Path(db_path)
        self.prices_ledger_path = Path(prices_ledger_path)
        self.router = router
        self.ledger_id = ledger_id

    def discover_active_commodities(self) -> List[Tuple[str, str]]:
        """Queries SQLite ledger_postings to find commodities currently held in portfolio."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT currency, 'USD' AS quote_currency
                FROM ledger_postings
                WHERE (account LIKE 'Assets:%Investments:%' OR account LIKE 'Assets:%Brokerage:%')
                """
            )
            return [(str(row[0]), str(row[1])) for row in cursor.fetchall()]

    def sync_watchlist(
        self,
        symbols: List[Tuple[str, str]] | None = None,
    ) -> Dict[str, Any]:
        targets = symbols or self.discover_active_commodities()
        if not targets:
            return {"status": "success", "synced_count": 0, "failed_symbols": []}

        collected: List[PriceDirectiveRecord] = []
        failed: List[str] = []

        for base, quote in targets:
            try:
                rec = self.router.resolve_quote(symbol=base, quote_currency=quote)
                collected.append(rec)
            except Exception as err:
                failed.append(f"{base}/{quote}: {err}")

        if collected:
            # 1. Plain-text file append with atomic flush & fsync
            self.prices_ledger_path.parent.mkdir(parents=True, exist_ok=True)
            directives_text = "\n".join(r.to_beancount_directive() for r in collected) + "\n"
            
            with open(self.prices_ledger_path, "a", encoding="utf-8") as f:
                f.write(directives_text)
                f.flush()
                os.fsync(f.fileno())

            # 2. SQLite projection update with schema enum alignment
            now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%f")
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.executemany(
                        """
                        INSERT INTO price_history (
                            ledger_id, id, directive_date, base_currency, quote_currency,
                            rate_numerator, rate_denominator, precision_scale, source, created_at
                        ) VALUES (
                            ?, 
                            (SELECT COALESCE(MAX(id), 0) + 1 FROM price_history WHERE ledger_id = ?),
                            ?, ?, ?, ?, ?, 4, 'POLLED_FEED', ?
                        )
                        ON CONFLICT(ledger_id, directive_date, base_currency, quote_currency) DO UPDATE SET
                            rate_numerator = excluded.rate_numerator,
                            rate_denominator = excluded.rate_denominator,
                            source = excluded.source,
                            created_at = excluded.created_at
                        """,
                        [
                            (
                                self.ledger_id,
                                self.ledger_id,
                                r.directive_date,
                                r.base_currency,
                                r.quote_currency,
                                r.price_numerator,
                                r.price_denominator,
                                now_ts,
                            )
                            for r in collected
                        ],
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        status = "success" if not failed else ("partial_failure" if collected else "failed")
        return {
            "status": status,
            "synced_count": len(collected),
            "failed_count": len(failed),
            "failed_symbols": failed,
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_price_scraper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/prices/scraper_daemon.py tests/test_price_scraper.py
git commit -m "feat(prices): add PriceScraperDaemon with atomic Beancount fsync and DB commit"
```

---

### Task 6: Shared FastMCP Tool & CLI Integration

**Files:**
- Modify: `src/ironledger/mcp/tools.py`
- Test: `tests/test_analytics.py`

**Interfaces:**
- Produces: `trigger_price_sync` FastMCP tool with audit logging

- [ ] **Step 1: Write failing test for MCP trigger_price_sync**

```python
# Add to tests/test_analytics.py
def test_mcp_trigger_price_sync(tmp_path):
    ledger_dir, projection_dir, db_path = setup_analytics_db(tmp_path)
    res = call_tool(
        "trigger_price_sync",
        {"symbols": ["AAPL", "BTC"], "quote_currency": "USD"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db_path,
    )
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])
    assert "status" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics.py::test_mcp_trigger_price_sync -v`
Expected: FAIL with `Unknown tool 'trigger_price_sync'`

- [ ] **Step 3: Update `src/ironledger/mcp/tools.py` to register `trigger_price_sync`**

Add `'trigger_price_sync'` to `ANALYTICS_TOOL_NAMES`, add inputSchema in `list_tools(include_analytics=True)`, and implement execution branch calling `PriceScraperDaemon` in `call_tool`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analytics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ironledger/mcp/tools.py tests/test_analytics.py
git commit -m "feat(mcp): add trigger_price_sync FastMCP tool with audit logging"
```

---

### Task 7: Full Regression Verification Suite

- [ ] **Step 1: Run complete pytest suite**

Run: `pytest`
Expected: 100% pass rate across all 950+ tests.

- [ ] **Step 2: Commit final milestone wrap**

```bash
git commit --allow-empty -m "chore(release): verify governed price feed daemon integration"
```
