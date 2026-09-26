"""Guard against corrupting ironledger.db via concurrent host CLI + docker
compose access. See src/ironledger/cli/compose_guard.py for the incident
this defends against."""

from __future__ import annotations

import io
import json
import subprocess

import pytest

from ironledger.cli.compose_guard import compose_service_running, warn_if_compose_running
from ironledger.cli.__main__ import _build_parser, _is_mutating_invocation


def _fake_run(records):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="\n".join(json.dumps(r) for r in records),
            stderr="",
        )

    return run


def test_compose_not_running_when_docker_missing(monkeypatch):
    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("no docker")

    monkeypatch.setattr(subprocess, "run", raise_missing)
    assert compose_service_running() is False


def test_compose_not_running_when_timeout(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=3)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert compose_service_running() is False


def test_compose_not_running_when_ps_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run([]))
    assert compose_service_running() is False


def test_compose_not_running_when_service_stopped(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run([{"Service": "ironledger", "State": "exited"}])
    )
    assert compose_service_running() is False


def test_compose_running_detected(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run([{"Service": "ironledger", "State": "running"}])
    )
    assert compose_service_running() is True


def test_compose_running_malformed_json_is_safe(monkeypatch):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="not json", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert compose_service_running() is False


def test_warn_if_compose_running_prints_and_returns_true(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run([{"Service": "ironledger", "State": "running"}])
    )
    stream = io.StringIO()
    assert warn_if_compose_running(stream=stream) is True
    assert "2026-09-24" in stream.getvalue()
    assert "docker compose down" in stream.getvalue()


def test_warn_if_compose_not_running_is_silent(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run([]))
    stream = io.StringIO()
    assert warn_if_compose_running(stream=stream) is False
    assert stream.getvalue() == ""


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["search", "x"], False),
        (["balances"], False),
        (["mcp"], False),
        (["compile"], True),
        (["compile", "status"], False),
        (["compile", "recover"], True),
        (["review", "list"], False),
        (["review", "approve", "1"], True),
        (["rule", "list"], False),
        (["fitid-trust", "list"], False),
        (["sync", "poll"], True),
        (["sync", "auth", "status"], False),
        (["sync", "auth", "claim"], True),
        (["prices", "poll"], True),
        (["web"], True),
        (["project", "status"], False),
        (["project"], True),
    ],
)
def test_is_mutating_invocation(argv, expected):
    parser = _build_parser()
    args = parser.parse_args(argv)
    assert _is_mutating_invocation(args) is expected
