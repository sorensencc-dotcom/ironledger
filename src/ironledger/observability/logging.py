"""Structured JSON log formatter with automated secret scrubbing."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from ironledger.security.scrubbing import SecretScrubber


class JsonLogFormatter(logging.Formatter):
    """Formats log records as structured JSON with integrated secret scrubbing."""

    def format(self, record: logging.LogRecord) -> str:
        # Format base message
        raw_message = record.getMessage()
        scrubbed_message = SecretScrubber.scrub_text(raw_message)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")

        log_data: Dict[str, Any] = {
            "timestamp": now_utc,
            "level": record.levelname,
            "logger": record.name,
            "message": scrubbed_message,
        }

        # Include standard context fields if present
        for attr in ("correlation_id", "ledger_id", "actor", "action", "provider_id"):
            if hasattr(record, attr):
                val = getattr(record, attr)
                if isinstance(val, dict):
                    log_data[attr] = SecretScrubber.scrub_dict(val)
                elif isinstance(val, str):
                    log_data[attr] = SecretScrubber.scrub_text(val)
                else:
                    log_data[attr] = val

        # Handle exception info if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            log_data["exception"] = SecretScrubber.scrub_text(exc_text)

        return json.dumps(log_data, separators=(",", ":"))
