CREATE VIEW IF NOT EXISTS v_portfolio_holdings AS
WITH ranked_prices AS (
    -- Resolve the most recent rational exchange rate per commodity using window function
    SELECT 
        base_currency AS commodity,
        quote_currency AS currency,
        rate_numerator AS price_numerator,
        rate_denominator AS price_denominator,
        directive_date AS as_of_date,
        ROW_NUMBER() OVER (
            PARTITION BY base_currency, quote_currency 
            ORDER BY directive_date DESC, id DESC
        ) AS rn
    FROM price_history
),
latest_prices AS (
    SELECT 
        commodity,
        currency,
        price_numerator,
        price_denominator,
        as_of_date
    FROM ranked_prices
    WHERE rn = 1
),
aggregated_lots AS (
    -- Aggregate holdings globally across account boundaries
    SELECT
        p.currency AS commodity,
        SUM(p.minor_units) AS total_units,
        COALESCE(SUM(p.minor_units), 0) AS total_cost_basis_minor_units,
        'USD' AS base_currency
    FROM ledger_postings p
    WHERE p.account LIKE 'Assets:%Investments:%'
       OR p.account LIKE 'Assets:%Brokerage:%'
    GROUP BY p.currency
)
SELECT
    a.commodity,
    a.total_units,
    a.total_cost_basis_minor_units,
    a.base_currency,
    COALESCE(lp.price_numerator, 1) AS price_numerator,
    COALESCE(lp.price_denominator, 1) AS price_denominator,
    -- Exact rational calculation with division-by-zero protection: (units * price_numerator) / price_denominator
    CAST((a.total_units * COALESCE(lp.price_numerator, 1)) / NULLIF(COALESCE(lp.price_denominator, 1), 1) AS INTEGER) AS market_value_minor_units,
    CAST((a.total_units * COALESCE(lp.price_numerator, 1)) / NULLIF(COALESCE(lp.price_denominator, 1), 1) AS INTEGER) - a.total_cost_basis_minor_units AS unrealized_gain_minor_units
FROM aggregated_lots a
LEFT JOIN latest_prices lp 
  ON lp.commodity = a.commodity 
 AND lp.currency = a.base_currency;
