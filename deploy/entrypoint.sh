#!/bin/sh
set -e

echo "[ironledger-init] Applying governed forward migrations..."
python3 -c "
import sqlite3
import os
from ironledger.db.migrations import migrate_governed

db_path = os.environ.get('IRONLEDGER_DB_PATH', '/app/data/ironledger.db')
os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA foreign_keys = ON;')
journal = os.environ.get('IRONLEDGER_JOURNAL_MODE', '').strip().upper()
if journal in {'WAL', 'DELETE', 'TRUNCATE', 'PERSIST', 'MEMORY'}:
    conn.execute(f'PRAGMA journal_mode = {journal}')
migrate_governed(conn)
conn.close()
print('[ironledger-init] Migrations verified successfully.')
"

echo "[ironledger-init] Starting service..."
exec "$@"
