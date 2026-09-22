"""Prometheus metrics endpoint for QA Platform.

Exposes /metrics via prometheus_client.  All metrics use the ``qap_`` prefix.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from qaplatform.observability.metrics import (
    http_request_duration,
    run_queue_depth,
    run_terminal_total,
    runs_in_flight,
)

# ── /metrics endpoint ─────────────────────────────────────────────────────────


async def metrics_endpoint(request: Request) -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


metrics_route = Route("/metrics", endpoint=metrics_endpoint, methods=["GET"])

__all__ = [
    "http_request_duration",
    "metrics_endpoint",
    "metrics_route",
    "run_queue_depth",
    "run_terminal_total",
    "runs_in_flight",
]
