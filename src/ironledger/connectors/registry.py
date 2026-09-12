"""Connector registry and execution dispatcher."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Type

from ironledger.connectors.base import BaseConnector
from ironledger.connectors.models import (
    ConnectorError,
    ConnectorProvider,
    ProtocolType,
    SyncResult,
)
from ironledger.connectors.ofx import OFXConnector
from ironledger.connectors.plaid import PlaidConnector
from ironledger.connectors.simplefin import SimpleFinConnector


class ConnectorRegistry:
    """Registry managing connector providers and instantiating protocol adapters."""

    def __init__(self):
        self._adapters: dict[ProtocolType, Type[BaseConnector]] = {
            ProtocolType.PLAID: PlaidConnector,
            ProtocolType.SIMPLEFIN: SimpleFinConnector,
            ProtocolType.OFX: OFXConnector,
        }
        self._instances: dict[str, BaseConnector] = {}

    def register_adapter(self, protocol_type: ProtocolType, adapter_cls: Type[BaseConnector]) -> None:
        self._adapters[protocol_type] = adapter_cls

    def save_provider(self, conn: sqlite3.Connection, provider: ConnectorProvider) -> None:
        conn.execute(
            """
            INSERT INTO connector_providers (
                provider_id, name, protocol_type, base_url, is_active,
                rate_limit_rpm, burst_capacity, config_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_id) DO UPDATE SET
                name = excluded.name,
                protocol_type = excluded.protocol_type,
                base_url = excluded.base_url,
                is_active = excluded.is_active,
                rate_limit_rpm = excluded.rate_limit_rpm,
                burst_capacity = excluded.burst_capacity,
                config_json = excluded.config_json
            """,
            (
                provider.provider_id,
                provider.name,
                provider.protocol_type.value,
                provider.base_url,
                1 if provider.is_active else 0,
                provider.rate_limit_rpm,
                provider.burst_capacity,
                json.dumps(provider.config),
                provider.created_at_utc,
            ),
        )

    def get_provider(self, conn: sqlite3.Connection, provider_id: str) -> ConnectorProvider | None:
        cur = conn.execute(
            """
            SELECT provider_id, name, protocol_type, base_url, is_active,
                   rate_limit_rpm, burst_capacity, config_json, created_at_utc
            FROM connector_providers WHERE provider_id = ?
            """,
            (provider_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        p_id, name, p_type, base_url, active, rpm, burst, cfg_json, created = row
        return ConnectorProvider(
            provider_id=p_id,
            name=name,
            protocol_type=ProtocolType(p_type),
            base_url=base_url,
            is_active=bool(active),
            rate_limit_rpm=rpm,
            burst_capacity=burst,
            config=json.loads(cfg_json),
            created_at_utc=created,
        )

    def get_connector(self, conn: sqlite3.Connection, provider_id: str) -> BaseConnector:
        if provider_id in self._instances:
            return self._instances[provider_id]

        provider = self.get_provider(conn, provider_id)
        if provider is None:
            raise ConnectorError(f"Provider '{provider_id}' not found in registry")

        adapter_cls = self._adapters.get(provider.protocol_type)
        if adapter_cls is None:
            raise ConnectorError(f"Unsupported protocol type: {provider.protocol_type}")

        instance = adapter_cls(provider=provider)
        self._instances[provider_id] = instance
        return instance

    def sync_provider(
        self,
        conn: sqlite3.Connection,
        ledger_id: str,
        provider_id: str,
        credentials: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> SyncResult:
        connector = self.get_connector(conn, provider_id)
        return connector.sync(
            conn=conn,
            ledger_id=ledger_id,
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
        )
