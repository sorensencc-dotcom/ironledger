"""Tests for CLI rendering of compile summary, status, and recovery reports."""

from __future__ import annotations

import json
from ironledger.compile.writer import CompileSummary
from ironledger.compile.recover import RecoveryDecision
from ironledger.cli.render import (
    render_compile_summary,
    render_recovery_report,
    render_compile_status,
)


def test_render_compile_summary():
    summary = CompileSummary(
        compile_run_id="crun-123",
        entry_count=42,
        year_files=("txns/2026.beancount",),
        output_hash="e" * 64,
    )
    out = render_compile_summary(summary)
    assert "crun-123" in out
    assert "42 entries" in out
    assert "e" * 64 in out


def test_render_recovery_report():
    rec = RecoveryDecision(action="recovered", compile_run_id="crun-123", detail="Finished atomic replace")
    out = render_recovery_report(rec)
    assert "Recovered compile run crun-123" in out


def test_render_compile_status_json():
    status_data = {
        "latest_run": {"compile_run_id": "crun-1", "status": "succeeded"},
        "active_run": None,
        "on_disk_hash": "a" * 64,
        "hash_matches": True,
    }
    out = render_compile_status(status_data, as_json=True)
    parsed = json.loads(out)
    assert parsed["latest_run"]["status"] == "succeeded"
    assert parsed["hash_matches"] is True
