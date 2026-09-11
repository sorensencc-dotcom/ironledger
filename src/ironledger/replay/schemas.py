"""JSON Schema Draft-07 validation for mutation payload types."""

from __future__ import annotations

from typing import Any
import jsonschema

from ironledger.replay.models import PayloadValidationError

STAGE_TRANSACTION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "ledger_id", "staged_transaction_id", "source_record_id",
        "proposed_date", "payee", "narration", "status",
        "identity_algo_version", "identity_method", "identity_fingerprint",
        "created_at_utc", "source_record", "postings"
    ],
    "additionalProperties": False,
    "properties": {
        "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
        "staged_transaction_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "source_record_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "proposed_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "payee": {"type": "string"},
        "narration": {"type": "string"},
        "status": {"type": "string", "enum": ["pending", "categorized", "approved", "rejected"]},
        "identity_algo_version": {"type": "integer", "minimum": 1},
        "identity_method": {"type": "string", "enum": ["fitid", "sha256_fallback"]},
        "identity_fingerprint": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "created_at_utc": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*Z$"},
        "source_record": {
            "type": "object",
            "required": ["source_document_id", "record_index", "canonical_payload", "content_sha256", "mime_type", "encoding", "provenance", "raw_payload_ref"],
            "additionalProperties": False,
            "properties": {
                "source_document_id": {"type": "string"},
                "record_index": {"type": "integer", "minimum": 0},
                "canonical_payload": {"type": "string"},
                "content_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "mime_type": {"type": "string"},
                "encoding": {"type": "string"},
                "provenance": {"type": "string"},
                "raw_payload_ref": {"type": "string"}
            }
        },
        "postings": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["staged_posting_id", "source_record_id", "role", "posting_index", "account", "minor_units", "currency", "minor_unit_scale", "created_at_utc"],
                "additionalProperties": False,
                "properties": {
                    "staged_posting_id": {"type": "string"},
                    "source_record_id": {"type": "string"},
                    "role": {"type": "string", "enum": ["imported", "contra"]},
                    "posting_index": {"type": "integer", "minimum": 0},
                    "account": {"type": ["string", "null"]},
                    "minor_units": {"type": "integer"},
                    "currency": {"type": "string", "pattern": "^[A-Z0-9_.-]{1,12}$"},
                    "minor_unit_scale": {"type": "integer", "minimum": 0, "maximum": 18},
                    "created_at_utc": {"type": "string"}
                }
            }
        }
    }
}

REVIEW_DECISION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["ledger_id", "staged_transaction_id", "prior_status", "new_status", "assigned_account", "rule_id", "reject_reason", "decided_at_utc"],
    "additionalProperties": False,
    "properties": {
        "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
        "staged_transaction_id": {"type": "string"},
        "prior_status": {"type": "string", "enum": ["pending", "categorized", "approved", "rejected"]},
        "new_status": {"type": "string", "enum": ["pending", "categorized", "approved", "rejected"]},
        "assigned_account": {"type": ["string", "null"]},
        "rule_id": {"type": ["string", "null"]},
        "reject_reason": {"type": ["string", "null"]},
        "decided_at_utc": {"type": "string"}
    }
}

COMPILE_LEDGER_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "ledger_id", "compile_run_id", "beancount_version", "compiler_version",
        "input_hash", "intended_output_hash", "actual_output_hash", "status",
        "compiled_tx_ids", "compiled_directives"
    ],
    "additionalProperties": False,
    "properties": {
        "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
        "compile_run_id": {"type": "string"},
        "beancount_version": {"type": "string"},
        "compiler_version": {"type": "string"},
        "input_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "intended_output_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "actual_output_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "status": {"type": "string", "enum": ["SUCCESS", "FAILED"]},
        "compiled_tx_ids": {"type": "array", "items": {"type": "string"}},
        "compiled_directives": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["proposed_date", "payee", "narration", "postings"],
                "additionalProperties": False,
                "properties": {
                    "proposed_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "payee": {"type": "string"},
                    "narration": {"type": "string"},
                    "postings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["account", "minor_units", "currency", "minor_unit_scale"],
                            "additionalProperties": False,
                            "properties": {
                                "account": {"type": "string"},
                                "minor_units": {"type": "integer"},
                                "currency": {"type": "string"},
                                "minor_unit_scale": {"type": "integer", "minimum": 0, "maximum": 18}
                            }
                        }
                    }
                }
            }
        }
    }
}

PRICE_DIRECTIVE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["ledger_id", "id", "directive_date", "base_currency", "quote_currency", "rate_numerator", "rate_denominator", "precision_scale", "source"],
    "additionalProperties": False,
    "properties": {
        "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
        "id": {"type": "integer"},
        "directive_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "base_currency": {"type": "string", "pattern": "^[A-Z0-9_.-]{1,12}$"},
        "quote_currency": {"type": "string", "pattern": "^[A-Z0-9_.-]{1,12}$"},
        "rate_numerator": {"type": "integer", "minimum": 1},
        "rate_denominator": {"type": "integer", "minimum": 1},
        "precision_scale": {"type": "integer", "minimum": 0, "maximum": 18},
        "source": {"type": "string", "enum": ["MANUAL", "POLLED_FEED", "EXCHANGE_API"]}
    }
}

RULE_UPDATE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["ledger_id", "rule_id", "action", "match_type", "pattern", "importing_account", "target_account", "priority", "active"],
    "additionalProperties": False,
    "properties": {
        "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
        "rule_id": {"type": "string"},
        "action": {"type": "string", "enum": ["CREATE", "UPDATE", "DELETE"]},
        "match_type": {"type": "string", "enum": ["exact", "prefix", "regex"]},
        "pattern": {"type": "string"},
        "importing_account": {"type": ["string", "null"]},
        "target_account": {"type": "string"},
        "priority": {"type": "integer"},
        "active": {"type": "integer", "enum": [0, 1]},
        "created_at_utc": {"type": "string"}
    }
}

SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    "STAGE_TRANSACTION": STAGE_TRANSACTION_SCHEMA,
    "REVIEW_DECISION": REVIEW_DECISION_SCHEMA,
    "COMPILE_LEDGER": COMPILE_LEDGER_SCHEMA,
    "PRICE_DIRECTIVE": PRICE_DIRECTIVE_SCHEMA,
    "RULE_UPDATE": RULE_UPDATE_SCHEMA,
}


def validate_payload_schema(event_type: str, payload: dict[str, Any], version: int = 1) -> None:
    """Validate payload against the registered Draft-07 JSON schema."""
    if event_type not in SCHEMA_REGISTRY:
        raise PayloadValidationError(f"Unknown event type: {event_type!r}")
    if version != 1:
        raise PayloadValidationError(f"Unsupported payload schema version: {version}")

    schema = SCHEMA_REGISTRY[event_type]
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as e:
        raise PayloadValidationError(f"Payload validation failed for {event_type}: {e.message}") from e
