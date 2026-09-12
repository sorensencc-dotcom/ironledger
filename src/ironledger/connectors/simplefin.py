"""SimpleFIN connector adapter."""

from __future__ import annotations

import datetime
import json
from typing import Any

from ironledger.connectors.base import BaseConnector
from ironledger.connectors.models import ConnectorRecord, PayloadParseError


class SimpleFinConnector(BaseConnector):
    """Connector adapter for SimpleFIN Bridge REST protocol."""

    def parse_payload(self, raw_data: Any) -> list[ConnectorRecord]:
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                raise PayloadParseError(f"Malformed SimpleFIN JSON string: {exc}") from exc

        if not isinstance(raw_data, dict) or "accounts" not in raw_data:
            raise PayloadParseError("SimpleFIN payload missing 'accounts' array")

        records: list[ConnectorRecord] = []
        for acct in raw_data.get("accounts", []):
            acct_id = str(acct.get("id", "default_acct"))
            currency = str(acct.get("currency", "USD"))

            for tx in acct.get("transactions", []):
                try:
                    tx_id = str(tx["id"])
                    posted_ts = int(tx["posted"])
                    date_str = datetime.datetime.fromtimestamp(posted_ts, datetime.timezone.utc).strftime("%Y-%m-%d")
                    amount_str = str(tx["amount"])

                    if "." in amount_str:
                        integer_part, frac_part = amount_str.split(".", 1)
                        frac_part = (frac_part + "00")[:2]
                        sign = -1 if integer_part.startswith("-") else 1
                        val = abs(int(integer_part)) * 100 + int(frac_part)
                        minor = sign * val
                    else:
                        minor = int(amount_str) * 100

                    payee = str(tx.get("payee") or tx.get("description") or "Unknown Payee")
                    memo = str(tx.get("memo") or "")

                    records.append(
                        ConnectorRecord(
                            record_id=tx_id,
                            account_id=acct_id,
                            posted_date=date_str,
                            amount_minor=minor,
                            currency=currency,
                            payee=payee,
                            memo=memo,
                            raw_payload=tx,
                        )
                    )
                except (KeyError, ValueError, TypeError) as exc:
                    raise PayloadParseError(f"Malformed SimpleFIN transaction: {exc}") from exc

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