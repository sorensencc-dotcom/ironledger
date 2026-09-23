DROP VIEW IF EXISTS v_portfolio_holdings;

CREATE VIEW v_portfolio_holdings AS
WITH ranked_prices AS (
    SELECT base_currency AS commodity, quote_currency AS currency,
           rate_numerator AS price_numerator, rate_denominator AS price_denominator,
           ROW_NUMBER() OVER (
               PARTITION BY base_currency, quote_currency
               ORDER BY directive_date DESC, id DESC
           ) AS rn
    FROM price_history
), aggregated_lots AS (
    SELECT commodity, SUM(remaining_units_minor) AS total_units,
           COALESCE(SUM(remaining_functional_cost_basis_minor), 0) AS total_cost_basis_minor_units,
           functional_currency AS base_currency
    FROM open_lots
    WHERE remaining_units_minor > 0
    GROUP BY commodity, functional_currency
)
SELECT a.commodity, a.total_units, a.total_cost_basis_minor_units, a.base_currency,
       CAST((a.total_units * COALESCE(p.price_numerator, 1)) /
            NULLIF(COALESCE(p.price_denominator, 1), 0) AS INTEGER) AS market_value_minor_units,
       CAST((a.total_units * COALESCE(p.price_numerator, 1)) /
            NULLIF(COALESCE(p.price_denominator, 1), 0) AS INTEGER) -
            a.total_cost_basis_minor_units AS unrealized_gain_minor_units
FROM aggregated_lots a
LEFT JOIN ranked_prices p ON p.commodity = a.commodity
                         AND p.currency = a.base_currency
                         AND p.rn = 1;
