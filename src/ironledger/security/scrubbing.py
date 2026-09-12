"""Automated secret and financial data scrubbing engine."""

from __future__ import annotations

import re
from typing import Any

_PAN_RE = re.compile(r"\b(?:4[0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{1,4}|5[1-5][0-9]{2}[ -]?[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}|3[47][0-9]{2}[ -]?[0-9]{6}[ -]?[0-9]{5}|6(?:011|5[0-9]{2})[ -]?[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}|[0-9]{4}[ -][0-9]{4}[ -][0-9]{4}[ -][0-9]{4})\b")
_CAP_TOKEN_RE = re.compile(r"il_cap_[0-9a-fA-F]{64}")
_SANDBOX_TOKEN_RE = re.compile(r"access-sandbox-[0-9a-fA-F-]+")
_BEARER_RE = re.compile(r"(?i)bearer\s+([A-Za-z0-9._~+/-]+=*)")
_SENSITIVE_KEYS = frozenset({"password", "secret", "api_key", "token", "access_token", "private_key", "client_secret"})


class SecretScrubber:
    """Filters and masks sensitive financial data and secrets from strings and dicts."""

    @classmethod
    def scrub_text(cls, text: str) -> str:
        if not text:
            return text
        # Mask PANs
        text = _PAN_RE.sub("[REDACTED_PAN]", text)
        # Mask capability tokens
        text = _CAP_TOKEN_RE.sub("il_cap_[REDACTED_TOKEN]", text)
        # Mask sandbox tokens
        text = _SANDBOX_TOKEN_RE.sub("access-sandbox-[REDACTED]", text)
        # Mask bearer tokens
        text = _BEARER_RE.sub("Bearer [REDACTED]", text)
        return text

    @classmethod
    def scrub_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in data.items():
            if any(s in k.lower() for s in _SENSITIVE_KEYS):
                result[k] = "[REDACTED]"
            elif isinstance(v, dict):
                result[k] = cls.scrub_dict(v)
            elif isinstance(v, list):
                result[k] = [cls.scrub_dict(item) if isinstance(item, dict) else cls.scrub_text(str(item)) if isinstance(item, str) else item for item in v]
            elif isinstance(v, str):
                result[k] = cls.scrub_text(v)
            else:
                result[k] = v
        return result
