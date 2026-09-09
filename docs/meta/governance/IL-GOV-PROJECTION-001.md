# IronLedger projection consistency contract

- **Document ID**: `IL-GOV-PROJECTION-001`
- **Status**: Ratified
- **Domain**: Data Consistency, Disposable SQLite Indexing, and Synchronization Latency
- **Enforcement Level**: Invariant / SLA Contract

---

## 1. Architectural principles

1. **Beancount Plaintext is Ground Truth**:
   - `projection.db` is purely a disposable cache for sub-millisecond FTS5 search, balances, and analytics.
   - Deleting `projection.db` results in zero data loss. It can be completely regenerated on demand via `ironledger project --rebuild`.

2. **Single-Writer Lock Protocol**:
   - SQLite writes to `projection.db` must hold a synchronous transaction or file lock during rebuilds.
   - Read queries executed by the API (`GET /api/balances`, `GET /api/search`) run in WAL mode with non-blocking reads.

---

## 2. Multi-threshold freshness contract & latency SLAs

The API and Top HUD evaluate projection latency $\Delta t = t_{\text{current}} - t_{\text{last\_rebuild}}$ against strict thresholds:

| Status | Latency $\Delta t$ | Indicator | Behavior |
|---|---|---|---|
| **`fresh` / Synced** | $< 5.0\text{s}$ | Emerald badge | Fast read queries permitted; full analytical confidence. |
| **`stale`** | $5.0\text{s} \le \Delta t \le 30.0\text{s}$ | Amber badge + Spinner | Background rebuild job queued; queries warn of pending updates. |
| **`critical` / Desync** | $> 30.0\text{s}$ or Hash Mismatch | Pulsing Rose alert | Operator alerted; automated compile blocked until rebuilt. |

---

## 3. Cryptographic hash comparison

Projection freshness is verified not only by timestamps but by output hash comparison:
$$\text{SHA-256}(\text{ledger\_disk\_files}) \stackrel{?}{=} \text{projection\_metadata.compiled\_hash}$$

When on-disk plaintext ledger files are edited directly outside the CLI, the hash comparison fails, transitioning projection status immediately to `critical` / `desync`.
