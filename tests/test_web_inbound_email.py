"""Inbound email webhook: HMAC, replay, and split-linker staging."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.events.signer import WebhookSigner
from ironledger.web.app import create_app

SECRET = "inbound-test-secret"
RECEIPT = (
    "From: User <user@gmail.com>\n"
    "To: sigil-inbox@ironledger.local\n"
    "Subject: Fwd: Amazon Order 114-1111111-2222222\n"
    "Date: Wed, 30 Sep 2026 10:00:00 -0400\n"
    "Content-Type: text/plain; charset=UTF-8\n"
    "\n"
    "---------- Forwarded message ---------\n"
    "From: auto-confirm@amazon.com\n"
    "Date: 2026-09-30\n"
    "Subject: Your Amazon Order 114-1111111-2222222\n"
    "To: user@gmail.com\n"
    "\n"
    "Order #114-1111111-2222222\n"
    "Item: Ergonomic Mouse Pad $15.00\n"
    "Item: USB Hub $25.00\n"
    "Subtotal: $40.00\n"
    "Tax: $3.20\n"
    "Total: $43.20\n"
)


def _client(tmp_path: Path, secret: str | None) -> tuple[TestClient, Path]:
    db_path = tmp_path / "ironledger.db"
    conn = connect(db_path)
    migrations.migrate(conn)
    conn.close()
    app = create_app(db_path=db_path)
    app.state.inbound_email_secret = secret
    return TestClient(app), db_path


def _signed(payload: str, *, delivery_id: str, timestamp: int | None = None) -> dict[str, str]:
    stamp = int(time.time()) if timestamp is None else timestamp
    header = WebhookSigner.build_signature_header(
        SECRET,
        stamp,
        "evt-inbound",
        delivery_id,
        payload,
    )
    return {"X-IronLedger-Signature": header}


def test_inbound_email_requires_secret(tmp_path: Path):
    client, _ = _client(tmp_path, None)
    response = client.post(
        "/api/webhooks/inbound-email",
        content=RECEIPT.encode("utf-8"),
        headers=_signed(RECEIPT, delivery_id="d1"),
    )
    assert response.status_code == 503


def test_inbound_email_rejects_bad_signature(tmp_path: Path):
    client, _ = _client(tmp_path, SECRET)
    response = client.post(
        "/api/webhooks/inbound-email",
        content=RECEIPT.encode("utf-8"),
        headers={"X-IronLedger-Signature": "t=1,e=evt,d=d1,v1=deadbeef"},
    )
    assert response.status_code == 401


def test_inbound_email_rejects_stale_signature(tmp_path: Path):
    client, _ = _client(tmp_path, SECRET)
    response = client.post(
        "/api/webhooks/inbound-email",
        content=RECEIPT.encode("utf-8"),
        headers=_signed(RECEIPT, delivery_id="d-stale", timestamp=int(time.time()) - 1000),
    )
    assert response.status_code == 401


def test_inbound_email_stages_once_and_rejects_replay(tmp_path: Path):
    client, db_path = _client(tmp_path, SECRET)
    headers = _signed(RECEIPT, delivery_id="d-once")
    first = client.post("/api/webhooks/inbound-email", content=RECEIPT.encode("utf-8"), headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert body["order_id"].startswith("ord_")
    assert body["source_document_id"]

    second = client.post("/api/webhooks/inbound-email", content=RECEIPT.encode("utf-8"), headers=headers)
    assert second.status_code == 409

    conn = connect(db_path)
    orders = conn.execute("SELECT COUNT(*) FROM itemized_orders").fetchone()[0]
    deliveries = conn.execute("SELECT COUNT(*) FROM inbound_email_deliveries").fetchone()[0]
    conn.close()
    assert orders == 1
    assert deliveries == 1
