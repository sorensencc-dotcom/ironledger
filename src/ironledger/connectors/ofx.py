"""OFX Direct Connect adapter."""

from __future__ import annotations

import re
from typing import Any

from ironledger.connectors.base import BaseConnector
from ironledger.connectors.models import ConnectorRecord, PayloadParseError


class OFXConnector(BaseConnector):
    """Connector adapter for OFX / QFX Direct Connect protocol."""

    def parse_payload(self, raw_data: Any) -> list[ConnectorRecord]:
        if not isinstance(raw_data, str):
            raise PayloadParseError("OFX raw payload must be string data")

        # Parse basic OFX STMTTRN blocks
        transactions: list[ConnectorRecord] = []
        stmt_blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", raw_data, re.DOTALL | re.IGNORECASE)

        for block in stmt_blocks:
            try:
                fitid_match = re.search(r"<FITID>(.*?)(?:<|\r|\n)", block, re.IGNORECASE)
                dtposted_match = re.search(r"<DTPOSTED>(\d{8})", block, re.IGNORECASE)
                trnamt_match = re.search(r"<TRNAMT>([-\d.]+)", block, re.IGNORECASE)
                name_match = re.search(r"<NAME>(.*?)(?:<|\r|\n)", block, re.IGNORECASE)
                memo_match = re.search(r"<MEMO>(.*?)(?:<|\r|\n)", block, re.IGNORECASE)

                if not (fitid_match and dtposted_match and trnamt_match):
                    continue

                fitid = fitid_match.group(1).strip()
                raw_dt = dtposted_match.group(1).strip()
                date_str = f"{raw_dt[:4]}-{raw_dt[4:6]}-{raw_dt[6:8]}"
                amount_str = trnamt_match.group(1).strip()

                if "." in amount_str:
                    integer_part, frac_part = amount_str.split(".", 1)
                    frac_part = (frac_part + "00")[:2]
                    sign = -1 if integer_part.startswith("-") else 1
                    val = abs(int(integer_part)) * 100 + int(frac_part)
                    minor = sign * val
                else:
                    minor = int(amount_str) * 100

                payee = name_match.group(1).strip() if name_match else "OFX Payee"
                memo = memo_match.group(1).strip() if memo_match else ""

                transactions.append(
                    ConnectorRecord(
                        record_id=fitid,
                        account_id="ofx_default",
                        posted_date=date_str,
                        amount_minor=minor,
                        currency="USD",
                        payee=payee,
                        memo=memo,
                        raw_payload={"fitid": fitid, "raw_block": block},
                    )
                )
            except Exception as exc:
                raise PayloadParseError(f"Failed parsing OFX block: {exc}") from exc

        return transactions

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