"""Startup and background lease reconciliation for abandoned webhook deliveries."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def reconcile_abandoned_deliveries(
    conn: sqlite3.Connection,
    now_iso: str | None = None,
) -> int:
    """Reverts expired PROCESSING deliveries back to PENDING state."""
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")

    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE webhook_deliveries
        SET status = 'PENDING',
            leased_by = NULL,
            leased_until_utc = NULL
        WHERE status = 'PROCESSING'
          AND leased_until_utc < ?;
        """,
        (now_iso,),
    )
    reconciled_count = cursor.rowcount
    conn.commit()
    return reconciled_count
