from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_TEST = ROOT / "tests" / "unit" / "test_config.py"
DOMAIN_MODELS_TEST = ROOT / "tests" / "unit" / "test_domain_models.py"
DISCOVERY_TEST = ROOT / "tests" / "unit" / "test_services" / "test_discovery.py"


def test_quality_ops_records_current_gate_settings_domain_validation_evidence():
    config_test = _read(CONFIG_TEST)
    domain_models_test = _read(DOMAIN_MODELS_TEST)
    discovery_test = _read(DISCOVERY_TEST)
    settings_validation_errors_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Settings validation errors 精确契约）"
    )
    domain_discovery_validation_errors_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Domain/discovery validation errors 精确契约）"
    )
    assert "`tests/unit/test_config.py` 66 passed" in (
        settings_validation_errors_exact_row
    )
    assert "Pydantic errors 的 `{type, loc, msg, input}` 单条投影" in (
        settings_validation_errors_exact_row
    )
    assert "numeric bounds、trusted_proxies" in settings_validation_errors_exact_row
    assert "required missing" in settings_validation_errors_exact_row
    assert "`any(...)` 找 loc 和消息片段" in (settings_validation_errors_exact_row)
    assert "某字段有相似错误文本" in settings_validation_errors_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in config_test
    assert "ENV_FIELD_NAMES = {" in config_test
    assert (
        "def _required_settings_input_without(missing_key: str) -> dict[str, str]:"
        in (config_test)
    )
    assert '"type": "greater_than_equal"' in config_test
    assert '"1.1", "less_than_equal", "Input should be less than or equal to 1"' in (
        config_test
    )
    assert '"type": expected_type' in config_test
    assert '"type": "missing"' in config_test
    assert (
        "log_level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL" in config_test
    )
    assert "assert any(" not in config_test
    assert 'expected_msg in error["msg"]' not in config_test
    assert (
        "`tests/unit/test_domain_models.py tests/unit/test_services/test_discovery.py` 18 passed"
        in (domain_discovery_validation_errors_exact_row)
    )
    assert "Pydantic errors 的 `{type, loc, msg, input}` 单条投影" in (
        domain_discovery_validation_errors_exact_row
    )
    assert "`string_too_short`" in domain_discovery_validation_errors_exact_row
    assert "`value_error`" in domain_discovery_validation_errors_exact_row
    assert "`too_long`" in domain_discovery_validation_errors_exact_row
    assert "`greater_than_equal`" in domain_discovery_validation_errors_exact_row
    assert "把 `ValidationError` 转成字符串后只找字段名和消息片段" in (
        domain_discovery_validation_errors_exact_row
    )
    assert "异常文本里有相似字段和消息" in (
        domain_discovery_validation_errors_exact_row
    )
    assert "def _validation_error_projection(errors) -> list[dict]:" in (
        domain_models_test
    )
    assert "def _validation_error_projection(errors) -> list[dict]:" in (discovery_test)
    assert '"type": "string_too_short"' in domain_models_test
    assert '"type": "too_long"' in domain_models_test
    assert '"type": "greater_than_equal"' in domain_models_test
    assert '"loc": ("retry_on", 0)' in domain_models_test
    assert '"loc": ("dedup_window_seconds",)' in domain_models_test
    assert '"input": too_many_retry_reasons' in domain_models_test
    assert '"type": "string_too_short"' in discovery_test
    assert '"type": "too_long"' in discovery_test
    assert '"loc": ("include_paths", 0)' in discovery_test
    assert '"loc": ("tags",)' in discovery_test
    assert '"input": too_many_include_paths' in discovery_test
    assert "error_text = str(exc_info.value)" not in domain_models_test
    assert "error_text = str(exc_info.value)" not in discovery_test
    assert "expected_location" not in domain_models_test
    assert "expected_location" not in discovery_test
    assert "expected_message" not in domain_models_test
    assert "expected_message" not in discovery_test
