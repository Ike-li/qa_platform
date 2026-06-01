"""Prometheus metric definitions for QA Platform."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

runs_in_flight = Gauge(
    "qap_runs_in_flight",
    "Number of runs currently in preparing/running/collecting state",
)

run_queue_depth = Gauge(
    "qap_run_queue_depth",
    "Number of runs in queued state (waiting to be dispatched)",
)

http_request_duration = Histogram(
    "qap_http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=["method", "route", "status_code"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

run_terminal_total = Counter(
    "qap_run_terminal_total",
    "Total number of runs that reached a terminal state",
    labelnames=["status"],
)

__all__ = [
    "http_request_duration",
    "run_queue_depth",
    "run_terminal_total",
    "runs_in_flight",
]
