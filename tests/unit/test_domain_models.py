from __future__ import annotations

from qaplatform.domain.models.common import (
    PaginatedResponse,
    PaginationParams,
    ResourceLimits,
)


def test_pagination_params_offset_uses_one_based_page_number():
    params = PaginationParams(page=3, per_page=25)

    assert params.offset == 50


def test_paginated_response_pages_rounds_up_and_handles_empty_results():
    assert PaginatedResponse[int](data=[1, 2], page=1, per_page=2, total=5).pages == 3
    assert PaginatedResponse[int](data=[], page=1, per_page=20, total=0).pages == 0


def test_resource_limits_defaults_match_safe_execution_baseline():
    limits = ResourceLimits()

    assert limits.memory_mb == 512
    assert limits.cpu_cores == 1.0
    assert limits.max_artifact_size_mb == 100
    assert limits.max_artifacts_count == 50
