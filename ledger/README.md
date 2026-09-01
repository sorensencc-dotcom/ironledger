# ledger/

Beancount is the sole accounting authority. This directory holds the canonical
ledger. It is written only by the compiler (Phase 3) through an atomic
temporary-file-to-rename operation, and only from operator-approved staged
transactions.

## Layout

| Path | Purpose |
|---|---|
| `ledger/main.beancount` | Root file. Include directives and global options only. No transactions. |
| `ledger/accounts.beancount` | Every account's `open` directive, each constrained to a single currency. |
| `ledger/txns/YYYY.beancount` | Compiled transaction entries, one file per calendar year. |

## Conventions (locked in Phase 1)

- Accounts: five Beancount roots (`Assets`, `Liabilities`, `Equity`, `Income`,
  `Expenses`); colon-separated PascalCase ASCII segments; minimum depth two.
- Currency: ISO-4217 alphabetic codes validated against the pinned table
  `src/ironledger/reference/iso4217.v2026-01.json`. Currency is part of monetary
  identity. Unlike currencies are never netted.
- Amounts: signed integer minor units plus an explicit currency and an explicit
  scale equal to the currency table's scale. No floating point.
- Timestamps: UTC, ISO-8601 with an explicit trailing `Z`.
- Source links: every entry and posting carries a source-document id, a
  source-record id, an immutable `identity_algo_version`, and an
  `identity_method` (`fitid` or `sha256_fallback`).

The concrete chart of accounts is deferred to the first authorized import
(Phase 0 decision D-6). Phase 1 locks the policy and the validation rules only.
