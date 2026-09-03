"""Phase 2a: ingest error hierarchy.

Verifies every ingest error subclasses a single base so callers can catch
IngestError, and that ParseError carries an optional row index.
"""

from __future__ import annotations

import pytest

from ironledger.ingest.errors import (
    AuthorizationError,
    ConfigError,
    IngestError,
    IngestPathError,
    ParseError,
    StageError,
)


@pytest.mark.parametrize(
    "exc_type",
    [IngestPathError, ParseError, StageError, ConfigError, AuthorizationError],
)
def test_every_ingest_error_subclasses_the_base(exc_type: type[Exception]):
    assert issubclass(exc_type, IngestError)


def test_parse_error_carries_optional_row_index():
    err = ParseError("bad amount on row 4", row_index=4)
    assert err.row_index == 4
    assert "row 4" in str(err)


def test_parse_error_row_index_defaults_to_none():
    assert ParseError("no row context").row_index is None
