"""Stage one RFC 822 receipt into evidence and the split linker."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ironledger.ingest.acquire import acquire
from ironledger.ingest.formats.email_receipt_engine import parse_email_receipt
from ironledger.ingest.split_linker import propose_splits_for_order


class InboundEmailError(ValueError):
    """The message was signed and accepted, but it is not a usable receipt."""


def stage_inbound_receipt(
    conn: sqlite3.Connection,
    raw_text: str,
    *,
    evidence_dir: Path,
    ledger_id: str,
) -> dict[str, str | None]:
    try:
        order = parse_email_receipt(raw_text)
    except Exception as exc:
        raise InboundEmailError(str(exc)) from exc

    evidence_dir.mkdir(parents=True, exist_ok=True)
    temporary = evidence_dir / f"inbound-{uuid.uuid4().hex}.eml"
    temporary.write_text(raw_text, encoding="utf-8")
    try:
        acquired = acquire(
            conn,
            temporary,
            evidence_dir=evidence_dir,
            provenance="inbound_email",
        )
        proposal_id = propose_splits_for_order(
            conn,
            order,
            acquired.source_document_id,
            ledger_id=ledger_id,
        )
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "source_document_id": acquired.source_document_id,
        "order_id": order.order_id,
        "proposal_id": proposal_id,
    }
