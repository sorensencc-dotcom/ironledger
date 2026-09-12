"""Pure-Python Prometheus and OpenMetrics compliant metrics registry."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple


class Metric:
    """Base metric class."""

    def __init__(self, name: str, documentation: str, label_names: Optional[List[str]] = None) -> None:
        self.name = name
        self.documentation = documentation
        self.label_names = tuple(label_names or [])
        self._lock = threading.Lock()


class Counter(Metric):
    """Monotonically increasing cumulative counter."""

    def __init__(self, name: str, documentation: str, label_names: Optional[List[str]] = None) -> None:
        super().__init__(name, documentation, label_names)
        self._values: Dict[Tuple[str, ...], int] = {}

    def inc(self, amount: int = 1, labels: Optional[Dict[str, str]] = None) -> None:
        if amount < 0:
            raise ValueError("Counter increments must be non-negative")
        label_tuple = tuple(labels.get(k, "") for k in self.label_names) if labels else ()
        with self._lock:
            self._values[label_tuple] = self._values.get(label_tuple, 0) + amount

    def get(self, labels: Optional[Dict[str, str]] = None) -> int:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names) if labels else ()
        with self._lock:
            return self._values.get(label_tuple, 0)

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.documentation}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            if not self._values:
                if not self.label_names:
                    lines.append(f"{self.name} 0")
            for label_tuple, val in sorted(self._values.items()):
                if self.label_names:
                    label_str = ",".join(f'{k}="{v}"' for k, v in zip(self.label_names, label_tuple))
                    lines.append(f"{self.name}{{{label_str}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return lines


class Gauge(Metric):
    """Instantaneous value metric capable of increasing and decreasing."""

    def __init__(self, name: str, documentation: str, label_names: Optional[List[str]] = None) -> None:
        super().__init__(name, documentation, label_names)
        self._values: Dict[Tuple[str, ...], int] = {}

    def set(self, value: int, labels: Optional[Dict[str, str]] = None) -> None:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names) if labels else ()
        with self._lock:
            self._values[label_tuple] = int(value)

    def inc(self, amount: int = 1, labels: Optional[Dict[str, str]] = None) -> None:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names) if labels else ()
        with self._lock:
            self._values[label_tuple] = self._values.get(label_tuple, 0) + amount

    def dec(self, amount: int = 1, labels: Optional[Dict[str, str]] = None) -> None:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names) if labels else ()
        with self._lock:
            self._values[label_tuple] = self._values.get(label_tuple, 0) - amount

    def get(self, labels: Optional[Dict[str, str]] = None) -> int:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names) if labels else ()
        with self._lock:
            return self._values.get(label_tuple, 0)

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.documentation}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            if not self._values:
                if not self.label_names:
                    lines.append(f"{self.name} 0")
            for label_tuple, val in sorted(self._values.items()):
                if self.label_names:
                    label_str = ",".join(f'{k}="{v}"' for k, v in zip(self.label_names, label_tuple))
                    lines.append(f"{self.name}{{{label_str}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return lines


class Histogram(Metric):
    """Histogram metric counting observations across rational latency buckets."""

    # Default latency boundaries in milliseconds
    DEFAULT_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)

    def __init__(
        self,
        name: str,
        documentation: str,
        label_names: Optional[List[str]] = None,
        buckets_ms: Optional[Tuple[int, ...]] = None,
    ) -> None:
        super().__init__(name, documentation, label_names)
        self.buckets_ms = tuple(sorted(buckets_ms or self.DEFAULT_BUCKETS_MS))
        self._counts: Dict[Tuple[str, ...], int] = {}
        self._sums_ms: Dict[Tuple[str, ...], int] = {}
        self._bucket_counts: Dict[Tuple[str, ...], Dict[int, int]] = {}

    def observe(self, duration_ms: int, labels: Optional[Dict[str, str]] = None) -> None:
        duration_ms = max(0, int(duration_ms))
        label_tuple = tuple(labels.get(k, "") for k in self.label_names) if labels else ()
        with self._lock:
            self._counts[label_tuple] = self._counts.get(label_tuple, 0) + 1
            self._sums_ms[label_tuple] = self._sums_ms.get(label_tuple, 0) + duration_ms

            if label_tuple not in self._bucket_counts:
                self._bucket_counts[label_tuple] = {b: 0 for b in self.buckets_ms}

            for b in self.buckets_ms:
                if duration_ms <= b:
                    self._bucket_counts[label_tuple][b] += 1

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.documentation}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            for label_tuple in sorted(self._counts.keys()):
                count = self._counts[label_tuple]
                sum_ms = self._sums_ms[label_tuple]
                b_counts = self._bucket_counts[label_tuple]

                base_label = ""
                if self.label_names:
                    base_label = ",".join(f'{k}="{v}"' for k, v in zip(self.label_names, label_tuple))

                cumulative = 0
                for b in self.buckets_ms:
                    cumulative = b_counts[b]
                    le_label = f'{base_label},le="{b}"' if base_label else f'le="{b}"'
                    lines.append(f"{self.name}_bucket{{{le_label}}} {cumulative}")

                inf_label = f'{base_label},le="+Inf"' if base_label else 'le="+Inf"'
                lines.append(f"{self.name}_bucket{{{inf_label}}} {count}")

                sum_label = f"{{{base_label}}}" if base_label else ""
                lines.append(f"{self.name}_sum{sum_label} {sum_ms}")
                lines.append(f"{self.name}_count{sum_label} {count}")
        return lines


class MetricsRegistry:
    """Thread-safe Prometheus / OpenMetrics registry."""

    def __init__(self) -> None:
        self._metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()

    def register(self, metric: Metric) -> Metric:
        with self._lock:
            if metric.name in self._metrics:
                return self._metrics[metric.name]
            self._metrics[metric.name] = metric
            return metric

    def counter(self, name: str, documentation: str, label_names: Optional[List[str]] = None) -> Counter:
        with self._lock:
            if name in self._metrics:
                m = self._metrics[name]
                if not isinstance(m, Counter):
                    raise TypeError(f"Metric {name} is already registered as {type(m).__name__}")
                return m
            c = Counter(name, documentation, label_names)
            self._metrics[name] = c
            return c

    def gauge(self, name: str, documentation: str, label_names: Optional[List[str]] = None) -> Gauge:
        with self._lock:
            if name in self._metrics:
                m = self._metrics[name]
                if not isinstance(m, Gauge):
                    raise TypeError(f"Metric {name} is already registered as {type(m).__name__}")
                return m
            g = Gauge(name, documentation, label_names)
            self._metrics[name] = g
            return g

    def histogram(
        self,
        name: str,
        documentation: str,
        label_names: Optional[List[str]] = None,
        buckets_ms: Optional[Tuple[int, ...]] = None,
    ) -> Histogram:
        with self._lock:
            if name in self._metrics:
                m = self._metrics[name]
                if not isinstance(m, Histogram):
                    raise TypeError(f"Metric {name} is already registered as {type(m).__name__}")
                return m
            h = Histogram(name, documentation, label_names, buckets_ms)
            self._metrics[name] = h
            return h

    def render_prometheus(self) -> str:
        lines: List[str] = []
        with self._lock:
            for name, metric in sorted(self._metrics.items()):
                rendered = metric.render()
                if rendered:
                    lines.extend(rendered)
        return "\n".join(lines) + "\n"


# Global Metric Registry & Pre-Registered Core Metrics
REGISTRY = MetricsRegistry()

HTTP_REQUESTS_TOTAL = REGISTRY.counter(
    "ironledger_http_requests_total",
    "Total HTTP requests received",
    label_names=["method", "path", "status"],
)

HTTP_REQUEST_DURATION_MS = REGISTRY.histogram(
    "ironledger_http_request_duration_ms",
    "HTTP request latency in integer milliseconds",
    label_names=["method", "path"],
)

CONNECTOR_SYNC_DURATION_MS = REGISTRY.histogram(
    "ironledger_connector_sync_duration_ms",
    "Connector synchronization execution latency in milliseconds",
    label_names=["provider_id", "status"],
)

CONNECTOR_RECORDS_STAGED_TOTAL = REGISTRY.counter(
    "ironledger_connector_records_staged_total",
    "Total financial records staged across connector sync runs",
    label_names=["provider_id", "ledger_id"],
)

RATE_LIMITER_TOKENS_AVAILABLE = REGISTRY.gauge(
    "ironledger_rate_limiter_tokens_available",
    "Available rate limiting tokens for connector provider",
    label_names=["provider_id"],
)

CIRCUIT_BREAKER_STATE = REGISTRY.gauge(
    "ironledger_circuit_breaker_state",
    "Circuit breaker state (0=Closed, 1=Half-Open, 2=Open)",
    label_names=["provider_id"],
)

EVENT_OUTBOX_QUEUE_DEPTH = REGISTRY.gauge(
    "ironledger_event_outbox_queue_depth",
    "Number of events pending delivery in outbox",
    label_names=["status"],
)

WEBHOOK_DELIVERY_FAILURES_TOTAL = REGISTRY.counter(
    "ironledger_webhook_delivery_failures_total",
    "Total webhook delivery failures per subscription",
    label_names=["subscription_id"],
)

TOKEN_AUTH_FAILURES_TOTAL = REGISTRY.counter(
    "ironledger_token_auth_failures_total",
    "Total token / capability authorization failures",
    label_names=["reason"],
)
