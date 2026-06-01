from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from qaplatform.domain.models.common import (
    PaginatedResponse,
    PaginationParams,
    ResourceLimits,
)
from qaplatform.domain.models.project import (
    CollectorDefinition,
    Pipeline,
    RetryPolicy,
    StageDefinition,
    TriggerConfig,
)


def _validation_error_projection(errors) -> list[dict]:
    return [
        {
            "type": error["type"],
            "loc": error["loc"],
            "msg": error["msg"],
            "input": error.get("input"),
        }
        for error in errors
    ]


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


def test_retry_policy_rejects_blank_and_unbounded_retry_reasons():
    too_many_retry_reasons = [f"reason-{index}" for index in range(21)]
    invalid_cases = [
        (
            {"retry_on": [""]},
            {
                "type": "string_too_short",
                "loc": ("retry_on", 0),
                "msg": "String should have at least 1 character",
                "input": "",
            },
        ),
        (
            {"retry_on": ["   "]},
            {
                "type": "value_error",
                "loc": ("retry_on",),
                "msg": "Value error, retry_on[0] must not be blank",
                "input": ["   "],
            },
        ),
        (
            {"retry_on": too_many_retry_reasons},
            {
                "type": "too_long",
                "loc": ("retry_on",),
                "msg": "List should have at most 20 items after validation, not 21",
                "input": too_many_retry_reasons,
            },
        ),
    ]

    for kwargs, expected_error in invalid_cases:
        with pytest.raises(ValidationError) as exc_info:
            RetryPolicy(**kwargs)
        assert _validation_error_projection(exc_info.value.errors()) == [
            expected_error
        ]


def test_trigger_config_rejects_blank_type_and_negative_dedup_window():
    invalid_cases = [
        (
            {"type": ""},
            {
                "type": "string_too_short",
                "loc": ("type",),
                "msg": "String should have at least 1 character",
                "input": "",
            },
        ),
        (
            {"type": "   "},
            {
                "type": "value_error",
                "loc": ("type",),
                "msg": "Value error, trigger_config type must not be blank",
                "input": "   ",
            },
        ),
        (
            {"type": "webhook", "dedup_window_seconds": -1},
            {
                "type": "greater_than_equal",
                "loc": ("dedup_window_seconds",),
                "msg": "Input should be greater than or equal to 0",
                "input": -1,
            },
        ),
    ]

    for kwargs, expected_error in invalid_cases:
        with pytest.raises(ValidationError) as exc_info:
            TriggerConfig(**kwargs)
        assert _validation_error_projection(exc_info.value.errors()) == [
            expected_error
        ]


def test_pipeline_domain_models_reject_blank_execution_text():
    invalid_cases = [
        (
            lambda: StageDefinition(name="   ", plugin="pytest"),
            {
                "type": "value_error",
                "loc": ("name",),
                "msg": "Value error, stage name must not be blank",
                "input": "   ",
            },
        ),
        (
            lambda: StageDefinition(name="Smoke", plugin="   "),
            {
                "type": "value_error",
                "loc": ("plugin",),
                "msg": "Value error, stage plugin must not be blank",
                "input": "   ",
            },
        ),
        (
            lambda: CollectorDefinition(plugin="   "),
            {
                "type": "value_error",
                "loc": ("plugin",),
                "msg": "Value error, collector plugin must not be blank",
                "input": "   ",
            },
        ),
        (
            lambda: Pipeline(id=uuid4(), project_id=uuid4(), name="   "),
            {
                "type": "value_error",
                "loc": ("name",),
                "msg": "Value error, pipeline name must not be blank",
                "input": "   ",
            },
        ),
    ]

    for build_model, expected_error in invalid_cases:
        with pytest.raises(ValidationError) as exc_info:
            build_model()
        assert _validation_error_projection(exc_info.value.errors()) == [
            expected_error
        ]
