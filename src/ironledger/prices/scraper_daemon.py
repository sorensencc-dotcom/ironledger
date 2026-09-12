from __future__ import annotations

import datetime
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ironledger.prices.router import PriceCascadeRouter


@contextmanager
def _exclusive_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            lock.write(b"0")
            lock.flush()
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            except PermissionError:
                # Closing the handle releases the Windows byte-range lock.
                pass
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


class PriceScraperDaemon:
    def __init__(self, db_path: Path, prices_ledger_path: Path, router: PriceCascadeRouter, ledger_id="default"):
        self.db_path, self.prices_ledger_path, self.router, self.ledger_id = Path(db_path), Path(prices_ledger_path), router, ledger_id

    def load_config_watchlist(self, config_path: Path | None = None) -> list[tuple[str, str]]:
        cfg_file = Path(config_path) if config_path else Path("config/prices.json")
        if not cfg_file.exists():
            return []
        import json
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            default_quote = str(data.get("quote_currency", "USD"))
            items = data.get("watchlist", [])
            targets: list[tuple[str, str]] = []
            for item in items:
                if isinstance(item, str):
                    targets.append((str(item), default_quote))
                elif isinstance(item, dict):
                    sym = item.get("symbol")
                    if sym:
                        targets.append((str(sym), str(item.get("quote_currency", default_quote))))
                elif isinstance(item, (list, tuple)) and len(item) == 2:
                    targets.append((str(item[0]), str(item[1])))
            return targets
        except Exception:
            return []

    def discover_active_commodities(self):
        with sqlite3.connect(self.db_path) as conn:
            return [(str(row[0]), "USD") for row in conn.execute("SELECT DISTINCT currency FROM ledger_postings WHERE account LIKE 'Assets:%Investments:%' OR account LIKE 'Assets:%Brokerage:%'")]

    def sync_watchlist(self, symbols=None, config_path: Path | None = None):
        if symbols is not None:
            targets = symbols
        else:
            cfg_targets = self.load_config_watchlist(config_path)
            targets = cfg_targets if cfg_targets else self.discover_active_commodities()
        collected, failed = [], []
        for base, quote in targets:
            try:
                collected.append(self.router.resolve_quote(base, quote))
            except Exception as exc:
                failed.append(f"{base}/{quote}: {exc}")
        if collected:
            self.prices_ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with _exclusive_lock(self.prices_ledger_path):
                with open(self.prices_ledger_path, "a", encoding="utf-8", newline="") as handle:
                    handle.write("\n".join(record.to_beancount_directive() for record in collected) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%f")
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                for record in collected:
                    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM price_history WHERE ledger_id=?", (self.ledger_id,)).fetchone()[0]
                    conn.execute("INSERT INTO price_history (id, ledger_id, directive_date, base_currency, quote_currency, rate_numerator, rate_denominator, precision_scale, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 4, 'POLLED_FEED', ?) ON CONFLICT(ledger_id, directive_date, base_currency, quote_currency) DO UPDATE SET rate_numerator=excluded.rate_numerator, rate_denominator=excluded.rate_denominator, source=excluded.source, created_at=excluded.created_at", (next_id, self.ledger_id, record.directive_date, record.base_currency, record.quote_currency, record.price_numerator, record.price_denominator, now))
                    conn.execute("INSERT INTO price_feed_audit (ledger_id, symbol, quote_currency, provider_id, status, rate_numerator, rate_denominator, latency_ms) VALUES (?, ?, ?, ?, 'SUCCESS', ?, ?, 0)", (self.ledger_id, record.base_currency, record.quote_currency, record.source_provider, record.price_numerator, record.price_denominator))
                conn.commit()
        return {"status": "success" if not failed else ("partial_failure" if collected else "failed"), "synced_count": len(collected), "failed_count": len(failed), "failed_symbols": failed}
