# Design Document: Governed Multi-Provider Commodity Price Feed Daemon

**Author:** Clare Codex / Antigravity / Autonomous Agents  
**Target Environment:** Python 3.12+, SQLite 3.45+ (WAL mode), Beancount v3 Plain-Text Authority, IronLedger Governance Runtime  
**Status:** Validated Design Spec  
**Date:** 2026-09-12  

---

## 1. Executive Summary

The **Governed Multi-Provider Commodity Price Feed Daemon** continuously resolves market valuation quotes for multi-asset commodities and currencies held in IronLedger portfolios. It operates under strict local-first governance guarantees:
- **Zero-Float Financial Math:** Strict ASCII decimal-to-integer rational parsing ($N/D$, where $N, D \in \mathbb{Z}$).
- **Plain-Text Ground Truth:** Appends canonical price directives directly to `ledger/prices.beancount`.
- **Atomic SQLite Projection:** Synchronizes price quotes directly to `price_history` with `INSERT ... ON CONFLICT DO UPDATE`.
- **Governed Network IO:** Governs all outbound provider calls via `TokenBucketRateLimiter` and `CircuitBreaker` (`BaseConnector`).
- **Deterministic Priority Cascade:** Falls back gracefully across providers (Yahoo $\to$ OpenStock $\to$ CoinGecko $\to$ Manual) with reciprocal rate calculation and 7-day staleness fail-closed defenses.

---

## 2. Architectural Invariants

1. **Zero Floating-Point Representation**:
   - Floating-point representations (`float`, `np.float64`) are prohibited in models, parsers, and arithmetic.
   - All conversions parse strings via `Decimal.as_tuple()` to exact integers `price_numerator` and `price_denominator`.
2. **Plain-Text Source of Truth**:
   - `ledger/prices.beancount` holds all canonical price records in standard Beancount syntax:
     ```beancount
     YYYY-MM-DD price <COMMODITY> <PRICE_DECIMAL> <QUOTE_CURRENCY>
     ```
3. **Multi-Ledger Isolation & Atomic Sync**:
   - Directives are stored per ledger in `price_history` keyed by `(ledger_id, directive_date, base_currency, quote_currency)`.
4. **Governed Connector Protection**:
   - Providers inherit from `ironledger.connectors.base.BaseConnector`, ensuring domain rate-limiting and circuit-breaker isolation against HTTP 429s or connection timeouts.
5. **Fail-Closed Staleness Boundary**:
   - Fallback terminates at a hard 7-day staleness boundary. If all live feeds fail and cached quotes exceed 7 days, the system raises `StalePriceDirectiveError` rather than interpolating synthetic prices.

---

## 3. Module Topology & Directory Structure

```text
src/ironledger/prices/
├── __init__.py
├── models.py                   # RationalRate, PriceDirectiveRecord
├── router.py                   # Priority cascade router & inverse rate evaluator
├── scraper_daemon.py           # Headless polling orchestrator & Beancount appender
└── providers/
    ├── __init__.py
    ├── base.py                 # Abstract BasePriceProvider wrapping BaseConnector
    ├── yahoo.py                # Yahoo Finance v8 JSON quote adapter
    ├── openstock.py            # OpenStock unauthenticated scraper adapter
    ├── coingecko.py            # CoinGecko REST v3 crypto rate adapter
    └── manual.py               # Local overrides / static test fixtures
src/ironledger/db/schema/
└── 0017_price_feed_audit.sql   # Execution audit trail for outbound quote resolution
tests/
├── test_price_models.py        # Rational conversion & zero-float AST validation
├── test_price_router.py        # Priority fallbacks & circuit breaker failovers
└── test_price_scraper.py       # End-to-end Beancount appending & DB synchronization
```

---

## 4. Detailed Component Design

### 4.1 Data Models (`src/ironledger/prices/models.py`)

- `PriceDirectiveRecord`:
  - `directive_date: str` (YYYY-MM-DD format)
  - `base_currency: str` (Commodity / Ticker, matching `^[A-Z0-9._-]{1,24}$`)
  - `quote_currency: str` (Currency, matching `^[A-Z]{3,8}$`)
  - `price_numerator: int` (Strictly $> 0$)
  - `price_denominator: int` (Strictly $> 0$)
  - `source_provider: str` (e.g. `"yahoo"`, `"openstock"`, `"coingecko"`, `"manual"`)
  - `raw_quote_str: str` (Original unparsed decimal string)

- Pure Zero-Float Parser:
  ```python
  @classmethod
  def from_decimal_str(
      cls,
      directive_date: str,
      base_currency: str,
      quote_currency: str,
      raw_price: str,
      source_provider: str,
  ) -> PriceDirectiveRecord:
      cleaned = raw_price.strip().replace(",", "")
      dec = Decimal(cleaned)
      if dec <= 0:
          raise ValueError(f"Price quote must be positive: {raw_price!r}")
      sign, digits, exponent = dec.as_tuple()
      numerator = int("".join(map(str, digits))) * (-1 if sign else 1)
      denominator = 10 ** abs(exponent) if exponent < 0 else 1
      return cls(
          directive_date=directive_date,
          base_currency=base_currency.upper(),
          quote_currency=quote_currency.upper(),
          price_numerator=numerator,
          price_denominator=denominator,
          source_provider=source_provider,
          raw_quote_str=cleaned,
      )
  ```

- Reciprocal Rate Evaluation:
  ```python
  def reciprocal(self, source_provider: str = "reciprocal") -> PriceDirectiveRecord:
      return PriceDirectiveRecord(
          directive_date=self.directive_date,
          base_currency=self.quote_currency,
          quote_currency=self.base_currency,
          price_numerator=self.price_denominator,
          price_denominator=self.price_numerator,
          source_provider=source_provider,
          raw_quote_str=f"{Decimal(self.price_denominator) / Decimal(self.price_numerator):.6f}",
      )
  ```

### 4.2 Provider Adapters (`src/ironledger/prices/providers/`)

- `BasePriceProvider(BaseConnector)`:
  - Base class wrapping `TokenBucketRateLimiter` and `CircuitBreaker`.
  - Abstract method `fetch_quote(symbol: str, quote_currency: str) -> PriceDirectiveRecord`.
- Concrete Adapters:
  - `YahooFinanceProvider`: Queries `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}` with rate limiter (60 RPM).
  - `OpenStockScraperProvider`: Queries unauthenticated equity feeds with 30 RPM limiter and failover circuit breaker.
  - `CoinGeckoProvider`: Queries `https://api.coingecko.com/api/v3/simple/price` with rate limiter (30 RPM).
  - `ManualProvider`: Returns verified local overrides for fixtures or test scenarios.

### 4.3 Cascading Router (`src/ironledger/prices/router.py`)

- `PriceCascadeRouter`:
  - Maintains priority chains per asset type.
  - Iterates through providers using `provider.circuit_breaker.execute(...)`.
  - Handles failover logging to `price_feed_audit`.
  - Attempts reciprocal rate calculation if direct quote is missing.
  - Enforces 7-day maximum staleness threshold before failing closed.

### 4.4 Scraper Daemon (`src/ironledger/prices/scraper_daemon.py`)

- Discovers active holdings from `ledger_postings` (`Assets:%Investments:%`, `Assets:%Brokerage:%`).
- Iterates over watchlist with fail-soft isolation (one symbol failure does not crash the run).
- Commits atomic SQLite updates using `executemany` with `ON CONFLICT DO UPDATE`.
- Appends canonical directives to `ledger/prices.beancount`.

### 4.5 Schema Migration (`0017_price_feed_audit.sql`)

```sql
CREATE TABLE IF NOT EXISTS price_feed_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default',
    symbol TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FALLTHROUGH_FAIL', 'CIRCUIT_OPEN', 'STALE_CACHED')),
    price_numerator INTEGER,
    price_denominator INTEGER,
    latency_ms INTEGER NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_price_feed_audit_symbol 
ON price_feed_audit (ledger_id, symbol, quote_currency, created_at DESC);
```

### 4.6 Shared FastMCP & CLI Integration

- **FastMCP Tool**: `trigger_price_sync` added to `src/ironledger/mcp/tools.py` with full audit trail logging.
- **CLI Commands**:
  - `ironledger prices sync [--symbols ...]`
  - `ironledger prices daemon [--interval-seconds ...]`

---

## 5. Verification Matrix

| Test Module | Coverage Area | Pass Criteria |
|---|---|---|
| `test_price_models.py` | Rational rate parser & zero-float AST | 100% integer types, exact reciprocal math, zero IEEE-754 floats |
| `test_price_router.py` | Priority cascade & circuit breaker | Tripped 429 fails over to secondary provider within same call |
| `test_price_scraper.py` | Beancount appending & DB projection | `bean-check` parses `prices.beancount` cleanly; SQLite rows updated |
| Full Test Suite | Regression invariance | 100% pass rate across all existing 949 tests + new tests |
