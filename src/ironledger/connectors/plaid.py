"""Plaid connector adapter."""

from __future__ import annotations

import json
from typing import Any

from ironledger.connectors.base import BaseConnector
from ironledger.connectors.models import ConnectorRecord, PayloadParseError


class PlaidConnector(BaseConnector):
    """Connector adapter for Plaid Transactions Sync API."""

    def parse_payload(self, raw_data: Any) -> list[ConnectorRecord]:
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                raise PayloadParseError(f"Malformed Plaid JSON string: {exc}") from exc

        if not isinstance(raw_data, dict) or "transactions" not in raw_data:
            raise PayloadParseError("Plaid payload missing 'transactions' field")

        records: list[ConnectorRecord] = []
        for tx in raw_data.get("transactions", []):
            try:
                tx_id = str(tx["transaction_id"])
                account_id = str(tx["account_id"])
                date_str = str(tx["date"])
                amount_num = tx["amount"]

                if isinstance(amount_num, (int, float)):
                    minor = int(round(amount_num * 100))
                else:
                    minor = int(amount_num)

                currency = str(tx.get("iso_currency_code") or "USD")
                payee = str(tx.get("name") or tx.get("merchant_name") or "Unknown")
                memo = str(tx.get("payment_channel") or "")

                records.append(
                    ConnectorRecord(
                        record_id=tx_id,
                        account_id=account_id,
                        posted_date=date_str,
                        amount_minor=minor,
                        currency=currency,
                        payee=payee,
                        memo=memo,
                        raw_payload=tx,
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise PayloadParseError(f"Malformed Plaid transaction: {exc}") from exc

        return records

    def fetch_transactions(
        self,
        credentials: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> list[ConnectorRecord]:
        raw_mock = credentials.get("mock_response")
        if raw_mock is not None:
            return self.parse_payload(raw_mock)
        return []