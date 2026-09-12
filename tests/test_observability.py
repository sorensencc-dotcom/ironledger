"""Comprehensive test suite for Phase 9 observability, metrics, and structured logging."""

from __future__ import annotations

import json
import logging
import sqlite3
import pytest
from fastapi.testclient import TestClient

from ironledger.db.migrations import migrate_governed
from ironledger.observability import (
    CIRCUIT_BREAKER_STATE,
    CONNECTOR_RECORDS_STAGED_TOTAL,
    CONNECTOR_SYNC_DURATION_MS,
    EVENT_OUTBOX_QUEUE_DEPTH,
    HTTP_REQUEST_DURATION_MS,
    HTTP_REQUESTS_TOTAL,
    RATE_LIMITER_TOKENS_AVAILABLE,
    REGISTRY,
    TOKEN_AUTH_FAILURES_TOTAL,
    WEBHOOK_DELIVERY_FAILURES_TOTAL,
    Counter,
    Gauge,
    Histogram,
    JsonLogFormatter,
    MetricsRegistry,
)
from ironledger.web.app import create_app


def test_metrics_counter_operations():
    registry = MetricsRegistry()
    c = registry.counter("test_counter_total", "Test counter help", label_names=["method", "status"])
    c.inc(1, labels={"method": "GET", "status": "200"})
    c.inc(5, labels={"method": "GET", "status": "200"})
    c.inc(2, labels={"method": "POST", "status": "201"})

    assert c.get(labels={"method": "GET", "status": "200"}) == 6
    assert c.get(labels={"method": "POST", "status": "201"}) == 2
    assert c.get(labels={"method": "DELETE", "status": "404"}) == 0

    rendered = "\n".join(c.render())
    assert "# HELP test_counter_total Test counter help" in rendered
    assert "# TYPE test_counter_total counter" in rendered
    assert 'test_counter_total{method="GET",status="200"} 6' in rendered
    assert 'test_counter_total{method="POST",status="201"} 2' in rendered


def test_metrics_gauge_operations():
    registry = MetricsRegistry()
    g = registry.gauge("test_gauge", "Test gauge help", label_names=["provider"])
    g.set(50, labels={"provider": "plaid"})
    assert g.get(labels={"provider": "plaid"}) == 50

    g.inc(10, labels={"provider": "plaid"})
    assert g.get(labels={"provider": "plaid"}) == 60

    g.dec(25, labels={"provider": "plaid"})
    assert g.get(labels={"provider": "plaid"}) == 35

    rendered = "\n".join(g.render())
    assert "# TYPE test_gauge gauge" in rendered
    assert 'test_gauge{provider="plaid"} 35' in rendered


def test_metrics_histogram_operations():
    registry = MetricsRegistry()
    h = registry.histogram(
        "test_latency_ms",
        "Test latency histogram",
        label_names=["route"],
        buckets_ms=(10, 50, 100),
    )
    h.observe(5, labels={"route": "/healthz"})
    h.observe(25, labels={"route": "/healthz"})
    h.observe(75, labels={"route": "/healthz"})
    h.observe(150, labels={"route": "/healthz"})

    rendered = "\n".join(h.render())
    assert "# TYPE test_latency_ms histogram" in rendered
    assert 'test_latency_ms_bucket{route="/healthz",le="10"} 1' in rendered
    assert 'test_latency_ms_bucket{route="/healthz",le="50"} 2' in rendered
    assert 'test_latency_ms_bucket{route="/healthz",le="100"} 3' in rendered
    assert 'test_latency_ms_bucket{route="/healthz",le="+Inf"} 4' in rendered
    assert 'test_latency_ms_sum{route="/healthz"} 255' in rendered
    assert 'test_latency_ms_count{route="/healthz"} 4' in rendered


def test_json_log_formatter_secret_scrubbing():
    formatter = JsonLogFormatter()
    logger = logging.getLogger("test.logger")

    record = logger.makeRecord(
        name="test.logger",
        level=logging.INFO,
        fn="test.py",
        lno=10,
        msg="Processing card 4111 1111 1111 1111 and token il_cap_1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "corr_123"
    record.ledger_id = "led_tenant1"

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert parsed["correlation_id"] == "corr_123"
    assert parsed["ledger_id"] == "led_tenant1"
    assert "[REDACTED_PAN]" in parsed["message"]
    assert "il_cap_[REDACTED_TOKEN]" in parsed["message"]
    assert "4111 1111 1111 1111" not in parsed["message"]


def test_metrics_scrape_endpoint_and_middleware(tmp_path):
    db = tmp_path / "test_obs.db"
    conn = sqlite3.connect(db)
    migrate_governed(conn, db)
    conn.close()

    app = create_app(db_path=db)
    client = TestClient(app)

    # Perform requests to generate metrics
    resp_health = client.get("/healthz")
    assert resp_health.status_code == 200
    assert "X-Correlation-ID" in resp_health.headers

    # Scrape /metrics
    resp_metrics = client.get("/metrics")
    assert resp_metrics.status_code == 200
    assert "text/plain" in resp_metrics.headers["content-type"]
    text = resp_metrics.text

    assert "ironledger_http_requests_total" in text
    assert 'path="/healthz"' in text
    assert "ironledger_http_request_duration_ms" in text
