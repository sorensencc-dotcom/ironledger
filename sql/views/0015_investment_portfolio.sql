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
    -- Open lots already carry normalized quantity and functional cost basis.
    SELECT
        l.commodity,
        SUM(l.remaining_units_minor) AS total_units,
        COALESCE(SUM(l.remaining_functional_cost_basis_minor), 0) AS total_cost_basis_minor_units,
        l.functional_currency AS base_currency
    FROM open_lots l
    WHERE l.remaining_units_minor > 0
    GROUP BY l.commodity, l.functional_currency
)
SELECT
    a.commodity,
    a.total_units,
    a.total_cost_basis_minor_units,
    a.base_currency,
    COALESCE(lp.price_numerator, 1) AS price_numerator,
    COALESCE(lp.price_denominator, 1) AS price_denominator,
    -- Exact rational calculation with division-by-zero protection: (units * price_numerator) / price_denominator
    CAST((a.total_units * COALESCE(lp.price_numerator, 1)) / NULLIF(COALESCE(lp.price_denominator, 1), 0) AS INTEGER) AS market_value_minor_units,
    CAST((a.total_units * COALESCE(lp.price_numerator, 1)) / NULLIF(COALESCE(lp.price_denominator, 1), 0) AS INTEGER) - a.total_cost_basis_minor_units AS unrealized_gain_minor_units
FROM aggregated_lots a
LEFT JOIN latest_prices lp 
  ON lp.commodity = a.commodity 
 AND lp.currency = a.base_currency;
