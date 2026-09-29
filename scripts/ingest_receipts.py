#!/usr/bin/env python3
"""
scripts/ingest_receipts.py
Ingests swept .eml email receipts into IronLedger's itemized orders and split proposal database.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import sqlite3

from ironledger.db.connection import connect
from ironledger.db.migrations import migrate
from ironledger.ingest.formats.email_receipt_engine import parse_email_receipt
from ironledger.ingest.split_linker import propose_splits_for_order


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest swept .eml email receipts into IronLedger itemized orders and split proposals."
    )
    parser.add_argument(
        "--receipts-dir",
        "-r",
        type=Path,
        default=Path("inbox/receipts"),
        help="Directory containing .eml files (default: inbox/receipts)",
    )
    parser.add_argument(
        "--db",
        default="ironledger.db",
        help="Path to SQLite ledger database (default: ironledger.db)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Maximum number of files to process (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and show summary without writing to the database",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.receipts-dir.exists() if hasattr(args, "receipts-dir") else not args.receipts_dir.exists():
        print(f"Error: receipts directory not found: {args.receipts_dir}", file=sys.stderr)
        return 1

    eml_files = sorted(args.receipts_dir.glob("*.eml"))
    total_files = len(eml_files)

    if not total_files:
        print(f"No .eml files found in {args.receipts_dir}.")
        return 0

    if args.limit:
        eml_files = eml_files[: args.limit]

    print(f"Processing {len(eml_files)} receipt files from {args.receipts_dir}...")

    conn = None
    if not args.dry_run:
        conn = connect(args.db)
        migrate(conn)

    parsed_count = 0
    parse_errors = 0
    split_proposals_created = 0
    orders_inserted = 0

    try:
        for idx, file_path in enumerate(eml_files, start=1):
            try:
                raw_text = file_path.read_text(encoding="utf-8", errors="replace")
                order = parse_email_receipt(raw_text)
                parsed_count += 1
            except Exception as exc:
                parse_errors += 1
                if idx <= 10 or idx % 500 == 0:
                    print(f"[{idx}/{len(eml_files)}] Parse skip {file_path.name}: {exc}", file=sys.stderr)
                continue

            if args.dry_run:
                if idx <= 5 or idx % 500 == 0:
                    print(f"[{idx}/{len(eml_files)}] [DRY RUN] Parsed {order.merchant} order {order.order_id} (${order.total_minor_units / 100:.2f}) with {len(order.lines)} item lines")
                continue

            # Ingest into SQLite database
            try:
                # Count proposals before
                cur = conn.execute("SELECT COUNT(*) FROM split_proposals WHERE order_id = ?", (order.order_id,))
                props_before = cur.fetchone()[0]

                proposal_id = propose_splits_for_order(conn, order)

                cur = conn.execute("SELECT COUNT(*) FROM split_proposals WHERE order_id = ?", (order.order_id,))
                props_after = cur.fetchone()[0]

                if props_after > props_before:
                    split_proposals_created += (props_after - props_before)
                orders_inserted += 1

                if idx <= 10 or idx % 500 == 0 or idx == len(eml_files):
                    print(f"[{idx}/{len(eml_files)}] Ingested {order.merchant} order {order.order_id} (${order.total_minor_units / 100:.2f}) - {len(order.lines)} lines")

            except Exception as exc:
                print(f"[{idx}/{len(eml_files)}] DB error for {file_path.name}: {exc}", file=sys.stderr)

        if not args.dry_run and conn:
            conn.commit()

        print("\nReceipt Ingestion Summary:")
        print(f"  Total files scanned:    {len(eml_files)}")
        print(f"  Successfully parsed:    {parsed_count}")
        print(f"  Parse skips/errors:     {parse_errors}")
        if not args.dry_run:
            print(f"  Orders stored in DB:    {orders_inserted}")
            print(f"  Split proposals matched:{split_proposals_created}")
            print(f"  Database path:          {Path(args.db).resolve()}")

        return 0

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
