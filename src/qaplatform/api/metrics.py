"""Prometheus metrics for QA Platform.

Exposes /metrics via prometheus_client.  All metrics use the ``qap_`` prefix.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

# ── Metric definitions ────────────────────────────────────────────────────────

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


# ── /metrics endpoint ─────────────────────────────────────────────────────────


async def metrics_endpoint(request: Request) -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


metrics_route = Route("/metrics", endpoint=metrics_endpoint, methods=["GET"])
