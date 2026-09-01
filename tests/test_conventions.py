"""Phase 1 task 1: canonical ledger convention fixture.

A supported account, currency, amount, UTC timestamp, and source link validate.
An unknown account, unknown currency, missing scale, malformed timestamp, and
invalid source reference are rejected.
"""

import pytest

from ironledger.conventions import (
    ConventionError,
    currency_scale,
    validate_account_name,
    validate_amount_minor_units,
    validate_convention_sample,
    validate_currency,
    validate_source_link,
    validate_utc_timestamp,
)


def good_sample() -> dict:
    return {
        "account": "Assets:Bank:Checking:Ally",
        "currency": "USD",
        "minor_units": -12345,
        "scale": 2,
        "timestamp": "2026-08-31T14:05:09Z",
        "source_link": {
            "source_document_id": "sha256:" + "a" * 64,
            "source_record_id": "rec-0001",
            "identity_algo_version": 1,
            "identity_method": "sha256_fallback",
        },
    }


def test_supported_sample_validates():
    validate_convention_sample(good_sample())  # must not raise


def test_unknown_account_root_rejected():
    sample = good_sample()
    sample["account"] = "Cash:Wallet"
    with pytest.raises(ConventionError):
        validate_convention_sample(sample)


def test_account_shallow_depth_rejected():
    with pytest.raises(ConventionError):
        validate_account_name("Assets")


def test_account_non_pascalcase_segment_rejected():
    with pytest.raises(ConventionError):
        validate_account_name("Assets:bank:Checking")


def test_unknown_currency_rejected():
    sample = good_sample()
    sample["currency"] = "XYZ"
    with pytest.raises(ConventionError):
        validate_convention_sample(sample)


def test_missing_scale_key_rejected():
    sample = good_sample()
    del sample["scale"]
    with pytest.raises(ConventionError):
        validate_convention_sample(sample)


def test_wrong_scale_for_currency_rejected():
    sample = good_sample()
    sample["currency"] = "JPY"  # table scale 0
    sample["scale"] = 2
    with pytest.raises(ConventionError):
        validate_convention_sample(sample)


def test_float_amount_rejected():
    with pytest.raises(ConventionError):
        validate_amount_minor_units(1.5, "USD", 2)


def test_bool_amount_rejected():
    with pytest.raises(ConventionError):
        validate_amount_minor_units(True, "USD", 2)


def test_malformed_timestamp_rejected():
    for bad in ("2026-08-31 14:05:09", "2026-08-31T14:05:09", "2026-08-31T14:05:09+00:00", "2026-13-01T00:00:00Z"):
        with pytest.raises(ConventionError):
            validate_utc_timestamp(bad)


def test_utc_timestamp_with_fraction_accepted():
    validate_utc_timestamp("2026-08-31T14:05:09.123456Z")


def test_invalid_source_reference_rejected():
    sample = good_sample()
    sample["source_link"]["source_document_id"] = ""
    with pytest.raises(ConventionError):
        validate_convention_sample(sample)


def test_unknown_identity_method_rejected():
    with pytest.raises(ConventionError):
        validate_source_link(
            {
                "source_document_id": "d",
                "source_record_id": "r",
                "identity_algo_version": 1,
                "identity_method": "guesswork",
            }
        )


def test_identity_algo_version_must_be_positive_int():
    with pytest.raises(ConventionError):
        validate_source_link(
            {
                "source_document_id": "d",
                "source_record_id": "r",
                "identity_algo_version": 0,
                "identity_method": "fitid",
            }
        )


def test_currency_scale_lookup():
    assert currency_scale("USD") == 2
    assert currency_scale("JPY") == 0
    assert currency_scale("KWD") == 3
    with pytest.raises(ConventionError):
        currency_scale("ZZZ")


def test_validate_currency_returns_code():
    assert validate_currency("EUR") == "EUR"
