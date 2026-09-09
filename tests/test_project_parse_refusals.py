from __future__ import annotations

from pathlib import Path

import pytest

from ironledger.project.errors import ProjectParseError
from ironledger.project.parse import parse_amount, parse_ledger
from tests.project_fixtures import make_sample_set, write_ledger, write_rendered_ledger


def _mutate_year(ledger_dir: Path, old: str, new: str) -> None:
    path = ledger_dir / "txns" / "2026.beancount"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def test_unknown_directive_raises_with_path_line_snippet(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    year = ledger_dir / "txns" / "2026.beancount"
    year.write_text(year.read_text(encoding="utf-8") + "plugin \"x\"\n", encoding="utf-8", newline="\n")
    with pytest.raises(ProjectParseError, match=r"txns/2026\.beancount:\d+:") as exc:
        parse_ledger(ledger_dir)
    assert "plugin" in str(exc.value)


def test_extra_metadata_key_raises(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    _mutate_year(ledger_dir, '    identity-method: "fitid"', '    identity-method: "fitid"\n    extra-key: "nope"')
    with pytest.raises(ProjectParseError, match="extra"):
        parse_ledger(ledger_dir)


def test_missing_required_metadata_raises(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    _mutate_year(ledger_dir, '  staged-transaction-id: "stx-1"\n', "")
    with pytest.raises(ProjectParseError, match="staged-transaction-id"):
        parse_ledger(ledger_dir)


def test_non_inverting_amount_raises():
    with pytest.raises(ProjectParseError):
        parse_amount("12.3", 2)
    with pytest.raises(ProjectParseError):
        parse_amount("12.345", 2)
    with pytest.raises(ProjectParseError):
        parse_amount("100.0", 0)


def test_include_set_disagrees_with_glob(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    extra = ledger_dir / "txns" / "2025.beancount"
    extra.write_text("", encoding="utf-8", newline="\n")
    with pytest.raises(ProjectParseError, match="include"):
        parse_ledger(ledger_dir)


def test_duplicate_staged_transaction_id(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    files = write_rendered_ledger(ledger_dir, make_sample_set())
    year = files["txns/2026.beancount"].decode("utf-8").rstrip() + "\n\n" + files["txns/2026.beancount"].decode("utf-8")
    write_ledger(ledger_dir, {**files, "txns/2026.beancount": year.encode("utf-8")})
    with pytest.raises(ProjectParseError, match="duplicate"):
        parse_ledger(ledger_dir)
