"""High-availability leader election, heartbeat tracking, and cluster federation."""

from __future__ import annotations

from ironledger.federation.election import (
    DEFAULT_LEASE_SECONDS,
    LeaderElectionEngine,
    LeaderFencedError,
    LeaderLease,
)
from ironledger.federation.heartbeat import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    HeartbeatMonitor,
    NodeHeartbeatRecord,
)

__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_SECONDS",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_STALE_THRESHOLD_SECONDS",
    "HeartbeatMonitor",
    "LeaderElectionEngine",
    "LeaderFencedError",
    "LeaderLease",
    "NodeHeartbeatRecord",
]
