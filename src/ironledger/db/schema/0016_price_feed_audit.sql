-- Migration 0016: Price Feed Outbound Resolution Audit Log

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
