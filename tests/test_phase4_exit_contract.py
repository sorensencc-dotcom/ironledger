# tests/test_phase4_exit_contract.py
"""Phase 4 exit-gate contract: one named test per spec §11 item 1–21 except 12."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ironledger.cli.__main__ import main
from ironledger.cli.auth import PROJECT_PHRASE
from ironledger.cli.render import render_balances
from ironledger.compile.errors import CompileLockedError
from ironledger.compile.hashing import compute_actual_output_hash, compute_input_hash
from ironledger.compile.model import ApprovedSet, ApprovedTransaction
from ironledger.compile.writer import acquire_compile_lock
from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.manifests import parse_manifest
from ironledger.project.activate import rebuild_projection
from ironledger.project.errors import (
    ProjectHashMismatchError,
    ProjectInputError,
    ProjectParseError,
)
from ironledger.project.parse import parse_amount, parse_ledger, discover_year_files
from ironledger.project.query import BalanceRow, assert_fresh, search
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


def _world(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir, "run-1")
    conn = connect(str(db_path))
    migrations.migrate(conn)
    return conn, ledger_dir, tmp_path / "projection", db_path


def _safe_off(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "safe-mode.json").write_text('{"enabled": false}', encoding="utf-8")
    return config_dir


def _sync_compile_hash(conn, ledger_dir: Path, compile_run_id: str = "run-1") -> str:
    actual = compute_actual_output_hash(ledger_dir, discover_year_files(ledger_dir))
    conn.execute(
        "UPDATE compile_runs SET actual_output_hash = ?, intended_output_hash = ? "
        "WHERE compile_run_id = ?",
        (actual, actual, compile_run_id),
    )
    conn.commit()
    return actual


def _mutate_year(ledger_dir: Path, old: str, new: str) -> None:
    path = ledger_dir / "txns" / "2026.beancount"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def _payload_digest(sqlite_path: Path) -> str:
    conn = connect(sqlite_path)
    try:
        hasher = hashlib.sha256()
        for sql in (
            "SELECT * FROM proj_accounts ORDER BY account",
            "SELECT * FROM proj_entries ORDER BY entry_id",
            "SELECT * FROM proj_postings ORDER BY posting_id",
            "SELECT * FROM proj_balances ORDER BY account, currency",
            "SELECT posting_id FROM proj_fts ORDER BY posting_id",
        ):
            for row in conn.execute(sql):
                hasher.update(repr(tuple(row)).encode("utf-8"))
                hasher.update(b"\n")
        return hasher.hexdigest()
    finally:
        conn.close()


def _row_counts(sqlite_path: Path) -> dict[str, int]:
    conn = connect(sqlite_path)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("proj_accounts", "proj_entries", "proj_postings", "proj_balances")
        }
    finally:
        conn.close()


def _fts_ids(sqlite_path: Path, query: str) -> list[str]:
    conn = connect(sqlite_path)
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT posting_id FROM proj_fts WHERE proj_fts MATCH ? ORDER BY posting_id",
                (query,),
            )
        ]
    finally:
        conn.close()


def _assert_path_line_snippet(exc: ProjectParseError) -> None:
    msg = str(exc)
    assert re.search(r":\d+:", msg), msg
    assert exc.snippet or any(token in msg for token in (exc.path, "amount")), msg


# 1. Render → write temp ledger → parse round trip
def test_contract_1_render_parse_round_trip(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    parsed = parse_ledger(ledger_dir)

    assert parsed.operating_currencies == ("USD",)
    accounts = {a.account: a for a in parsed.accounts}
    assert accounts["Assets:Checking"].currency == "USD"
    assert accounts["Assets:Checking"].open_date == "2026-09-01"
    assert accounts["Expenses:Food"].currency == "USD"
    assert accounts["Expenses:Food"].open_date == "2026-09-01"

    assert len(parsed.entries) == 1
    entry = parsed.entries[0]
    assert entry.entry_date == "2026-09-01"
    assert entry.payee == 'Coffee "Shop"\\Cafe'
    assert entry.narration == "Latte"
    imported, contra = entry.postings
    assert imported.account == "Assets:Checking"
    assert imported.minor_units == -1234
    assert imported.minor_unit_scale == 2
    assert imported.currency == "USD"
    assert imported.source_document_id == "doc-1"
    assert imported.source_record_id == "rec-1"
    assert imported.identity_algo_version == 1
    assert imported.identity_method == "fitid"
    assert contra.account == "Expenses:Food"
    assert contra.minor_units == 1234
    assert contra.minor_unit_scale == 2


# 2. Parse refusals leave live projection byte-identical
def test_contract_2_parse_refusals_leave_live_untouched(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    live = (projection_dir / "projection.sqlite").read_bytes()

    def _parse_copy(mutator) -> None:
        copy = tmp_path / "parse-copy"
        write_rendered_ledger(copy, make_sample_set())
        mutator(copy)
        with pytest.raises(ProjectParseError) as exc:
            parse_ledger(copy)
        _assert_path_line_snippet(exc.value)

    _parse_copy(
        lambda d: (d / "txns" / "2026.beancount").write_text(
            (d / "txns" / "2026.beancount").read_text(encoding="utf-8") + 'plugin "x"\n',
            encoding="utf-8",
            newline="\n",
        )
    )
    _parse_copy(
        lambda d: _mutate_year(
            d, '    identity-method: "fitid"', '    identity-method: "fitid"\n    extra-key: "nope"'
        )
    )
    _parse_copy(lambda d: _mutate_year(d, '  staged-transaction-id: "stx-1"\n', ""))
    _parse_copy(lambda d: _mutate_year(d, "-12.34", "-12.3"))
    with pytest.raises(ProjectParseError):
        parse_amount("12.3", 2)

    year = ledger_dir / "txns" / "2026.beancount"
    year.write_text(year.read_text(encoding="utf-8") + 'plugin "x"\n', encoding="utf-8", newline="\n")
    with pytest.raises((ProjectParseError, ProjectHashMismatchError)):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == live
    conn.close()


# 3. proj_balances equals SUM(proj_postings) per (account, currency)
def test_contract_3_balances_equal_sum(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    live = connect(projection_dir / "projection.sqlite")
    rows = live.execute(
        "SELECT b.account, b.currency, b.minor_units, "
        " (SELECT SUM(p.minor_units) FROM proj_postings p "
        "  WHERE p.account = b.account AND p.currency = b.currency) "
        "FROM proj_balances b"
    ).fetchall()
    assert rows
    for account, currency, bal, summed in rows:
        assert bal == summed, (account, currency, bal, summed)
    live.close()
    conn.close()


# 4. Second currency on one account refused; balances never nets two currencies
def test_contract_4_second_currency_refused(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    live = (projection_dir / "projection.sqlite").read_bytes()
    accounts = ledger_dir / "accounts.beancount"
    accounts.write_text(
        accounts.read_text(encoding="utf-8") + "2026-09-01 open Assets:Checking EUR\n",
        encoding="utf-8",
        newline="\n",
    )
    _sync_compile_hash(conn, ledger_dir)
    with pytest.raises((ProjectInputError, ProjectParseError)):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == live

    human = render_balances(
        [
            BalanceRow("Assets:Checking", -1234, "USD", 2),
            BalanceRow("Assets:Checking", -100, "EUR", 2),
        ],
        as_json=False,
    )
    assert "USD" in human and "EUR" in human
    assert human.count("Assets:Checking") == 2
    assert human.count("\n") == 1
    conn.close()


# 5. Delete live sqlite+manifest and rebuild: identical payload digest
def test_contract_5_delete_and_rebuild_identical_payload(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    sqlite_path = projection_dir / "projection.sqlite"
    manifest_path = projection_dir / "projection.manifest.json"
    counts = _row_counts(sqlite_path)
    fts_hits = _fts_ids(sqlite_path, "Coffee")
    digest = _payload_digest(sqlite_path)
    assert fts_hits

    sqlite_path.unlink()
    manifest_path.unlink()
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T13:00:00Z")
    assert _row_counts(sqlite_path) == counts
    assert _fts_ids(sqlite_path, "Coffee") == fts_hits
    assert _payload_digest(sqlite_path) == digest
    conn.close()


# 6. FTS columns match; narration rewrite changes the hit set
def test_contract_6_fts_columns_and_rebuild_changes_hits(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    sqlite_path = projection_dir / "projection.sqlite"
    seeded = _fts_ids(sqlite_path, "Latte")
    assert seeded
    assert _fts_ids(sqlite_path, "Coffee")  # payee
    assert _fts_ids(sqlite_path, "Checking")  # account
    assert _fts_ids(sqlite_path, "fitid")  # posting_text

    sample = make_sample_set()
    mocha_tx: ApprovedTransaction = replace(sample.transactions[0], narration="Mocha")
    mocha_set = ApprovedSet(transactions=(mocha_tx,))
    write_rendered_ledger(ledger_dir, mocha_set)
    actual = compute_actual_output_hash(ledger_dir, discover_year_files(ledger_dir))
    input_hash = compute_input_hash(mocha_set)
    conn.execute(
        "UPDATE compile_runs SET actual_output_hash = ?, intended_output_hash = ?, input_hash = ? "
        "WHERE compile_run_id = ?",
        (actual, actual, input_hash, "run-1"),
    )
    conn.commit()
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert _fts_ids(sqlite_path, "Latte") == []
    assert _fts_ids(sqlite_path, "Mocha")
    conn.close()


# 7. Crash before sqlite replace: previous live (or absent)
def test_contract_7_crash_before_sqlite_replace(tmp_path: Path, monkeypatch):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    real = os.replace

    def boom_sqlite(src, dst):
        if Path(dst).name == "projection.sqlite":
            raise KeyboardInterrupt("simulated crash")
        return real(src, dst)

    monkeypatch.setattr("ironledger.project.activate.os.replace", boom_sqlite)
    with pytest.raises(KeyboardInterrupt):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    assert not (projection_dir / "projection.sqlite").exists()

    monkeypatch.setattr("ironledger.project.activate.os.replace", real)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    previous = (projection_dir / "projection.sqlite").read_bytes()
    monkeypatch.setattr("ironledger.project.activate.os.replace", boom_sqlite)
    with pytest.raises(KeyboardInterrupt):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == previous
    conn.close()


# 8. Crash between replaces: status not fresh-ok; search/balances exit 1
def test_contract_8_crash_between_replaces_fail_closed(tmp_path: Path, monkeypatch, capsys):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    real = os.replace

    def boom_manifest(src, dst):
        if Path(dst).name == "projection.manifest.json":
            raise KeyboardInterrupt("simulated crash")
        return real(src, dst)

    monkeypatch.setattr("ironledger.project.activate.os.replace", boom_manifest)
    with pytest.raises(KeyboardInterrupt):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    conn.close()

    rc_status = main(
        [
            "--ledger-dir",
            str(ledger_dir),
            "project",
            "status",
            "--projection-dir",
            str(projection_dir),
        ]
    )
    status_out = capsys.readouterr().out.lower()
    fresh_ok = rc_status == 0 and "project status: ok" in status_out and "hash matches files: yes" in status_out
    assert not fresh_ok
    assert rc_status != 0 or "mismatch" in status_out or "hash matches files: no" in status_out

    assert (
        main(
            [
                "--ledger-dir",
                str(ledger_dir),
                "search",
                "--projection-dir",
                str(projection_dir),
                "Coffee",
            ]
        )
        == 1
    )
    assert (
        main(
            [
                "--ledger-dir",
                str(ledger_dir),
                "balances",
                "--projection-dir",
                str(projection_dir),
            ]
        )
        == 1
    )


# 9. Safe mode / wrong phrase deny project; search/balances/status skip require_operator
def test_contract_9_auth_surface(tmp_path: Path, capsys):
    conn, ledger_dir, projection_dir, db_path = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    config_off = _safe_off(tmp_path)
    safe_on = tmp_path / "config-safe"
    safe_on.mkdir()

    rc_safe = main(
        [
            "--db",
            str(db_path),
            "--config-dir",
            str(safe_on),
            "project",
            "--ledger-dir",
            str(ledger_dir),
            "--projection-dir",
            str(projection_dir),
            "--confirm",
            PROJECT_PHRASE,
        ]
    )
    assert rc_safe == 3
    capsys.readouterr()

    rc_wrong = main(
        [
            "--db",
            str(db_path),
            "--config-dir",
            str(config_off),
            "project",
            "--ledger-dir",
            str(ledger_dir),
            "--projection-dir",
            str(projection_dir),
            "--confirm",
            "wrong phrase",
        ]
    )
    assert rc_wrong == 3
    capsys.readouterr()

    audit = connect(str(db_path))
    denied = audit.execute(
        "SELECT result FROM audit_events WHERE result = 'denied'"
    ).fetchall()
    assert len(denied) >= 2
    audit.close()

    with patch("ironledger.cli.auth.require_operator") as spy:
        assert (
            main(
                [
                    "--ledger-dir",
                    str(ledger_dir),
                    "search",
                    "--projection-dir",
                    str(projection_dir),
                    "Coffee",
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "--ledger-dir",
                    str(ledger_dir),
                    "balances",
                    "--projection-dir",
                    str(projection_dir),
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "--ledger-dir",
                    str(ledger_dir),
                    "project",
                    "status",
                    "--projection-dir",
                    str(projection_dir),
                ]
            )
            == 0
        )
        spy.assert_not_called()


# 10. New compile hash without project → search/balances stale
def test_contract_10_stale_after_new_compile(tmp_path: Path, capsys):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    orig_hash = conn.execute(
        "SELECT actual_output_hash FROM compile_runs WHERE compile_run_id = 'run-1'"
    ).fetchone()[0]
    (ledger_dir / "accounts.beancount").write_bytes(
        (ledger_dir / "accounts.beancount").read_bytes() + b"; touched\n"
    )
    new_hash = compute_actual_output_hash(ledger_dir, discover_year_files(ledger_dir))
    conn.execute(
        "INSERT INTO compile_runs (compile_run_id, beancount_version, compiler_version, "
        " input_hash, intended_output_hash, actual_output_hash, status, started_at_utc, "
        " finished_at_utc, recovery_state) "
        "VALUES ('run-2', '3.2.3', '0.1.0', ?, ?, ?, 'succeeded', "
        " '2026-09-08T13:00:00Z', '2026-09-08T13:00:01Z', 'none')",
        ("c" * 64, new_hash, new_hash),
    )
    conn.commit()
    conn.close()

    search_argv = [
        "--ledger-dir",
        str(ledger_dir),
        "search",
        "--projection-dir",
        str(projection_dir),
        "Coffee",
    ]
    assert main(search_argv) == 1
    err = capsys.readouterr().err
    assert "--ledger-dir" in err
    assert '--confirm "authorize project"' in err
    assert new_hash[:12] in err
    assert orig_hash[:12] in err
    assert (
        main(
            [
                "--ledger-dir",
                str(ledger_dir),
                "balances",
                "--projection-dir",
                str(projection_dir),
            ]
        )
        == 1
    )
    err_bal = capsys.readouterr().err
    assert "--ledger-dir" in err_bal
    assert '--confirm "authorize project"' in err_bal


# 11. No import beancount under src/ironledger
def test_contract_11_no_import_beancount():
    root = Path("src") / "ironledger"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("import beancount") or stripped.startswith("from beancount"):
                offenders.append(f"{path}:{i}:{line}")
    assert offenders == []


# 13. search and balances parse and run with no --db
def test_contract_13_search_balances_without_db(tmp_path: Path, capsys):
    conn, ledger_dir, projection_dir, db_path = _world(tmp_path)
    config_dir = _safe_off(tmp_path)
    conn.close()
    assert (
        main(
            [
                "--config-dir",
                str(config_dir),
                "--db",
                str(db_path),
                "project",
                "--ledger-dir",
                str(ledger_dir),
                "--projection-dir",
                str(projection_dir),
                "--confirm",
                PROJECT_PHRASE,
            ]
        )
        == 0
    )
    capsys.readouterr()
    search_argv = [
        "--ledger-dir",
        str(ledger_dir),
        "search",
        "--projection-dir",
        str(projection_dir),
        "Coffee",
    ]
    bal_argv = [
        "--ledger-dir",
        str(ledger_dir),
        "balances",
        "--projection-dir",
        str(projection_dir),
    ]
    assert "--db" not in search_argv and "--db" not in bal_argv
    assert main(search_argv) == 0
    assert "Coffee" in capsys.readouterr().out
    assert main(bal_argv) == 0
    out = capsys.readouterr().out
    assert "Assets:Checking" in out
    assert "-1234" in out


# 14. --help lists project/search/balances; epilog is README golden path
def test_contract_14_help_and_epilog(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "project" in out
    assert "search" in out
    assert "balances" in out
    assert "python -m ironledger.cli" in out
    assert "authorize project" in out
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "python -m ironledger.cli project" in readme
    assert "python -m ironledger.cli search" in readme
    assert "python -m ironledger.cli balances" in readme
    assert "python -m ironledger.cli project --db <db> --ledger-dir ledger" in out
    assert "python -m ironledger.cli search --ledger-dir ledger coffee" in out
    assert "python -m ironledger.cli balances --ledger-dir ledger" in out


# 15. README argv smoke: search/balances with --ledger-dir and no --db
def test_contract_15_readme_argv_smoke(tmp_path: Path, capsys):
    conn, ledger_dir, projection_dir, db_path = _world(tmp_path)
    config_dir = _safe_off(tmp_path)
    conn.close()
    assert (
        main(
            [
                "--db",
                str(db_path),
                "--config-dir",
                str(config_dir),
                "project",
                "--ledger-dir",
                str(ledger_dir),
                "--projection-dir",
                str(projection_dir),
                "--confirm",
                PROJECT_PHRASE,
            ]
        )
        == 0
    )
    with pytest.raises(SystemExit):
        main(["--help"])
    help_out = capsys.readouterr().out
    assert "project" in help_out and "search" in help_out and "balances" in help_out
    assert (
        main(
            [
                "--ledger-dir",
                str(ledger_dir),
                "search",
                "--projection-dir",
                str(projection_dir),
                "coffee",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--ledger-dir",
                str(ledger_dir),
                "balances",
                "--projection-dir",
                str(projection_dir),
            ]
        )
        == 0
    )


# 16. include glob mismatch through rebuild; live unchanged
def test_contract_16_include_glob_mismatch(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    live = (projection_dir / "projection.sqlite").read_bytes()
    extra = ledger_dir / "txns" / "2025.beancount"
    extra.write_text("", encoding="utf-8", newline="\n")
    _sync_compile_hash(conn, ledger_dir)
    with pytest.raises(ProjectParseError, match="include"):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == live
    conn.close()


# 17. Duplicate staged-transaction-id
def test_contract_17_duplicate_stx_id(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    live = (projection_dir / "projection.sqlite").read_bytes()
    year = ledger_dir / "txns" / "2026.beancount"
    body = year.read_text(encoding="utf-8")
    year.write_text(body.rstrip() + "\n\n" + body, encoding="utf-8", newline="\n")
    _sync_compile_hash(conn, ledger_dir)
    with pytest.raises(ProjectParseError, match="duplicate"):
        rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == live
    conn.close()


# 18. Held compile lock refuses project; live unchanged
def test_contract_18_held_compile_lock(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    live = (projection_dir / "projection.sqlite").read_bytes()
    with acquire_compile_lock(ledger_dir):
        with pytest.raises(CompileLockedError):
            rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:01:00Z")
    assert (projection_dir / "projection.sqlite").read_bytes() == live
    conn.close()


# 19. Manifest schema_version equals projection_meta.schema_version == 1
def test_contract_19_manifest_schema_version(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    manifest = parse_manifest(
        (projection_dir / "projection.manifest.json").read_text(encoding="utf-8")
    )
    live = connect(projection_dir / "projection.sqlite")
    meta_schema = live.execute(
        "SELECT schema_version FROM projection_meta WHERE singleton = 1"
    ).fetchone()[0]
    live.close()
    assert manifest.schema_version == meta_schema == 1
    conn.close()


# 20. Two search runs after one rebuild return identical rows
def test_contract_20_search_order_stable(tmp_path: Path):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    qconn = assert_fresh(ledger_dir, projection_dir)
    rows1 = search(qconn, "Coffee", limit=50, offset=0)
    rows2 = search(qconn, "Coffee", limit=50, offset=0)
    assert rows1 == rows2
    pairs = [(h.entry_date, h.posting_id) for h in rows1]
    assert pairs == sorted(pairs)
    qconn.close()


# 21. Empty and invalid FTS via CLI: exit 1, no Traceback
def test_contract_21_empty_and_invalid_fts(tmp_path: Path, capsys):
    conn, ledger_dir, projection_dir, _db = _world(tmp_path)
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    base = [
        "--ledger-dir",
        str(ledger_dir),
        "search",
        "--projection-dir",
        str(projection_dir),
    ]
    assert main(base + [""]) == 1
    empty = capsys.readouterr()
    assert "Traceback" not in empty.out and "Traceback" not in empty.err
    assert "empty" in (empty.out + empty.err).lower()
    assert main(base + ["AND"]) == 1
    invalid = capsys.readouterr()
    assert "Traceback" not in invalid.out and "Traceback" not in invalid.err
    assert "invalid" in (invalid.out + invalid.err).lower()
