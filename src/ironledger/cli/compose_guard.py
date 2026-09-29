"""Fail-safe warning against corrupting IronLedger's SQLite database via
concurrent access from a host CLI invocation and a running `docker compose`
container that share the same bind-mounted database file.

Real incident, 2026-09-24: `docker-compose.yml` was changed (`ef57d81`,
"share host DB in compose") so the host CLI and the containerized web
server both see the same `ironledger.db` through a bind mount. SQLite's
WAL mode is documented as unsafe over non-local filesystems, and a Docker
Desktop bind mount on Windows behaves like one for locking purposes. The
database went malformed the next day and needed a manual `sqlite3
.recover` pass (see `.recovery-work/`, git-ignored).

This check is advisory-only and fail-safe: any failure to determine
compose state (no `docker` binary, no compose project, timeout, ...) is
treated as "not running" so a host CLI operator is never blocked by an
environment quirk. It warns; it does not refuse to run.
"""

from __future__ import annotations

import json
import subprocess
import sys

_TIMEOUT_SECONDS = 3


def compose_service_running(service: str = "ironledger") -> bool:
    """Best-effort check: is the named docker-compose service currently up?

    Returns False (never raises) on any error — see module docstring.
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except (json.JSONDecodeError, ValueError):
        return False
    return any(
        rec.get("Service") == service and str(rec.get("State", "")).lower().startswith("running")
        for rec in records
    )


def warn_if_compose_running(*, stream=None) -> bool:
    """Print a loud warning if the compose service shares this host's DB file.

    Returns True if a warning was printed, purely so callers/tests can assert
    on it. The command is never blocked — see module docstring.
    """
    if not compose_service_running():
        return False
    target = stream if stream is not None else sys.stderr
    try:
        print(
            "WARNING: docker compose service 'ironledger' appears to be running "
            "and shares this host's ironledger.db via bind mount. Writing from "
            "both the host CLI and the container at once risks corrupting the "
            "database (this happened once, 2026-09-24). Stop compose first "
            "(`docker compose down`) or run this command inside the container "
            "(`docker compose exec ironledger ironledger ...`).",
            file=target,
        )
    except (ValueError, OSError):
        pass
    return True
