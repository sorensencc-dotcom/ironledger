#!/usr/bin/env python3
"""
scripts/sweep_receipts.py
Sweeps raw .eml receipts from Gmail via IMAP into ironledger's inbox/receipts/.
"""

import argparse
import email
from email.utils import parsedate_to_datetime
import getpass
import imaplib
import os
from pathlib import Path
import re
import sys


DEFAULT_QUERY = (
    'label:"Grocery Receipts" OR label:"Receipt Summary" OR '
    'from:(auto-confirm@amazon.com OR venmo@venmo.com OR no_reply@email.apple.com OR '
    'uber.us@uber.com OR receipts@*.com OR no-reply@exact.publix.com) OR '
    'subject:("order confirmation" OR "receipt" OR "your order" OR "invoice")'
)


def sanitize(text: str, max_len: int = 40) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", text)
    cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._-")
    return cleaned[:max_len] if cleaned else "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep receipt emails from Gmail via IMAP for IronLedger ingestion."
    )
    parser.add_argument(
        "--user",
        "-u",
        default=os.getenv("GMAIL_USER", "sorensencc@gmail.com"),
        help="Gmail address (default: env GMAIL_USER or sorensencc@gmail.com)",
    )
    parser.add_argument(
        "--password",
        "-p",
        default=os.getenv("GMAIL_APP_PASSWORD"),
        help="16-character Google App Password (default: env GMAIL_APP_PASSWORD)",
    )
    parser.add_argument(
        "--query",
        "-q",
        default=DEFAULT_QUERY,
        help="Gmail search query string (uses X-GM-RAW syntax)",
    )
    parser.add_argument(
        "--out-dir",
        "-o",
        type=Path,
        default=Path("inbox/receipts"),
        help="Directory to save .eml files (default: inbox/receipts)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Maximum number of messages to fetch (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and list matches without downloading files",
    )
    parser.add_argument(
        "--add-label",
        default=None,
        help="Optional Gmail label to add after downloading (e.g. 'IronLedger-Processed')",
    )
    parser.add_argument(
        "--remove-label",
        default=None,
        help="Optional Gmail label to remove after downloading (e.g. 'Z-Receipts')",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    app_password = args.password
    if not app_password:
        app_password = getpass.getpass(f"Google App Password for {args.user}: ")

    if not app_password:
        print("Error: Google App Password is required.", file=sys.stderr)
        return 1

    app_password = app_password.replace(" ", "")

    print(f"Connecting to imap.gmail.com:993 as {args.user}...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(args.user, app_password)
    except Exception as e:
        print(f"IMAP authentication failed: {e}", file=sys.stderr)
        return 1

    try:
        needs_write = bool(args.add_label or args.remove_label)
        mail.select('"[Gmail]/All Mail"', readonly=not needs_write)

        print(f"Executing search: {args.query}")
        escaped_query = args.query.replace("\\", "\\\\").replace('"', '\\"')
        status, data = mail.uid("SEARCH", "X-GM-RAW", f'"{escaped_query}"')
        if status != "OK" or not data or not data[0]:
            print("No matching messages found.")
            return 0

        uids = data[0].split()
        total_found = len(uids)
        print(f"Found {total_found} matching messages.")

        if args.limit:
            uids = uids[-args.limit:]
            print(f"Bounded to latest {len(uids)} messages.")

        if args.dry_run:
            print("[DRY RUN] Skipping file download.")
            return 0

        args.out_dir.mkdir(parents=True, exist_ok=True)

        downloaded = 0
        skipped = 0

        for idx, uid_bytes in enumerate(uids, start=1):
            uid = uid_bytes.decode("ascii")

            # Check if this UID was already exported
            existing = list(args.out_dir.glob(f"*_{uid}.eml"))
            if existing:
                skipped += 1
                continue

            status, fetch_data = mail.uid("fetch", uid_bytes, "(RFC822)")
            if status != "OK" or not fetch_data:
                print(f"[{idx}/{len(uids)}] Failed to fetch UID {uid}", file=sys.stderr)
                continue

            raw_eml = None
            for part in fetch_data:
                if isinstance(part, tuple) and len(part) == 2:
                    raw_eml = part[1]
                    break

            if not raw_eml:
                continue

            msg = email.message_from_bytes(raw_eml)
            subject = sanitize(msg.get("Subject", "no_subject"))
            sender = sanitize(msg.get("From", "unknown_sender"))

            date_str = "00000000"
            date_header = msg.get("Date")
            if date_header:
                try:
                    dt = parsedate_to_datetime(date_header)
                    date_str = dt.strftime("%Y%m%d")
                except Exception:
                    pass

            filename = f"{date_str}_{sender}_{subject}_{uid}.eml"
            dest_path = args.out_dir / filename

            dest_path.write_bytes(raw_eml)
            downloaded += 1

            if args.add_label:
                mail.uid("STORE", uid_bytes, "+X-GM-LABELS", f'("{args.add_label}")')
            if args.remove_label:
                mail.uid("STORE", uid_bytes, "-X-GM-LABELS", f'("{args.remove_label}")')

            print(f"[{idx}/{len(uids)}] Saved: {filename}")

        print("\nSweep Complete:")
        print(f"  Total matched:     {total_found}")
        print(f"  Newly downloaded:  {downloaded}")
        print(f"  Already existed:   {skipped}")
        print(f"  Output directory:  {args.out_dir.resolve()}")
        if args.add_label:
            print(f"  Added label:       {args.add_label}")
        if args.remove_label:
            print(f"  Removed label:     {args.remove_label}")
        return 0

    finally:
        try:
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
