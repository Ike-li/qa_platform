from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_config_evidence():
    env_vars_truncated_ciphertext_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Env vars truncated ciphertext 解密容错契约）"
    )
    encryption_keys_rotation_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Encryption keys rotation 配置边界契约）"
    )
    required_config_blank_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Required config blank values 启动期契约）"
    )
    log_config_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Log config invalid value 启动期契约）"
    )
    numeric_config_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Numeric config invalid bounds 启动期契约）"
    )
    trusted_proxies_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Trusted proxies CIDR 启动期契约）"
    )
    default_string_config_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Default string config blank 启动期契约）"
    )
    assert "`tests/unit/test_services/test_env_vars_crypto.py` 6 passed" in (
        env_vars_truncated_ciphertext_row
    )
    assert "coverage unit 1332 passed" in env_vars_truncated_ciphertext_row
    assert "短于 header/nonce/tag 的 envelope" in env_vars_truncated_ciphertext_row
    assert "统一脱敏 `ValueError`" in env_vars_truncated_ciphertext_row
    assert "只覆盖 AAD mismatch 与 key rotation" in env_vars_truncated_ciphertext_row
    assert "base64 合法但 envelope 为空时冒出 `IndexError`" in (
        env_vars_truncated_ciphertext_row
    )
    assert "3 个红灯" in env_vars_truncated_ciphertext_row
    assert "避免 env_vars crypto 测试只证明正常密文和错 AAD" in (
        env_vars_truncated_ciphertext_row
    )
    assert (
        "`tests/unit/test_config.py::test_encryption_keys_rotation_values_are_validated "
        "tests/unit/test_dependencies.py::test_crypto_service_rejects_non_256_bit_keys_before_encrypt` "
        "7 passed"
    ) in encryption_keys_rotation_row
    assert "coverage unit 1339 passed" in encryption_keys_rotation_row
    assert "非 64 hex" in encryption_keys_rotation_row
    assert "0-15" in encryption_keys_rotation_row
    assert "非 32 bytes key" in encryption_keys_rotation_row
    assert "旧配置测试只覆盖默认 `encryption_key`" in encryption_keys_rotation_row
    assert "延迟到首次加密才失败" in encryption_keys_rotation_row
    assert "7 个红灯" in encryption_keys_rotation_row
    assert "避免密钥轮换测试只证明 happy rotation" in encryption_keys_rotation_row
    assert (
        "`tests/unit/test_config.py::test_required_string_fields_reject_blank_values` 6 passed"
        in (required_config_blank_row)
    )
    assert "coverage unit 1345 passed" in required_config_blank_row
    assert "空白 database_url" in required_config_blank_row
    assert "redis_url" in required_config_blank_row
    assert "S3 endpoint/access/secret" in required_config_blank_row
    assert "whitespace-only jwt_secret" in required_config_blank_row
    assert "旧必填配置用例只删除环境变量" in required_config_blank_row
    assert "32 个空格的 JWT secret" in required_config_blank_row
    assert "延迟到依赖初始化/运行时失败" in required_config_blank_row
    assert "6 个红灯" in required_config_blank_row
    assert "避免 required config 测试只证明字段不存在会失败" in (
        required_config_blank_row
    )
    assert (
        "`tests/unit/test_config.py::test_log_configuration_rejects_invalid_values` 4 passed"
        in (log_config_row)
    )
    assert "coverage unit 1349 passed" in log_config_row
    assert "非法或空白 `log_level` / `log_format`" in log_config_row
    assert "合法 log level 归一为大写" in log_config_row
    assert "合法 log format 归一为小写" in log_config_row
    assert "旧 logging 测试只覆盖 json/console happy path" in log_config_row
    assert "`QAP_LOG_LEVEL=verbose`" in log_config_row
    assert "`QAP_LOG_FORMAT=yaml` 静默退成 console" in log_config_row
    assert "4 个红灯" in log_config_row
    assert "避免 logging 配置测试只证明正常格式能启动" in log_config_row
    assert (
        "`tests/unit/test_config.py::test_numeric_settings_reject_invalid_bounds` 19 passed"
        in (numeric_config_row)
    )
    assert "coverage unit 1368 passed" in numeric_config_row
    assert "DB/Redis/S3/JWT/timeout/rate-limit/retention" in numeric_config_row
    assert "0 或负值" in numeric_config_row
    assert "`database_max_overflow=0` 保持合法" in numeric_config_row
    assert "旧配置测试只覆盖整数能从 env 读出正值" in numeric_config_row
    assert "pool/TTL/rate limit/retention" in numeric_config_row
    assert "延迟到 DB engine、Redis、JWT、限流或清理任务运行时失败" in (
        numeric_config_row
    )
    assert "19 个红灯" in numeric_config_row
    assert "避免 numeric config 测试只证明 happy parse" in numeric_config_row
    assert (
        "`tests/unit/test_config.py::test_trusted_proxies_reject_invalid_cidrs tests/unit/test_config.py::test_trusted_proxies_accept_valid_cidrs_and_strip_whitespace` 4 passed"
        in (trusted_proxies_row)
    )
    assert "coverage unit 1372 passed" in trusted_proxies_row
    assert "空白或非法 `trusted_proxies` CIDR" in trusted_proxies_row
    assert "规整合法 CIDR 两端空白" in trusted_proxies_row
    assert "rate limit 用例只覆盖合法 CIDR 下的 XFF 解析" in (trusted_proxies_row)
    assert "`_parse_trusted_nets()` 只打一条 warning 并跳过配置" in (
        trusted_proxies_row
    )
    assert "按代理 IP 桶限流或忽略真实客户端 IP" in trusted_proxies_row
    assert "3 个红灯和 1 个正向契约" in trusted_proxies_row
    assert "避免 trusted proxy 测试只证明 happy CIDR" in trusted_proxies_row
    assert (
        "`tests/unit/test_config.py::test_default_string_settings_reject_blank_values tests/unit/test_config.py::test_otel_exporter_endpoint_blank_is_treated_as_unset tests/unit/test_config.py::test_cors_origins_reject_blank_entries tests/unit/test_config.py::test_cors_origins_strip_whitespace` 7 passed"
        in (default_string_config_row)
    )
    assert "coverage unit 1379 passed" in default_string_config_row
    assert "空白 S3 bucket/region、Docker host、OTel service name 与 CORS origin" in (
        default_string_config_row
    )
    assert "合法 CORS origin 会 strip" in default_string_config_row
    assert "空白 OTel exporter endpoint 继续按未配置处理" in (default_string_config_row)
    assert "兼容 `.env` 默认" in default_string_config_row
    assert "旧配置测试只覆盖默认值能读出" in default_string_config_row
    assert "延迟到 S3、Docker、OTel resource 或 CORS middleware 运行期失败" in (
        default_string_config_row
    )
    assert "`.env` 里空白 OTel exporter endpoint 本就是未配置语义" in (
        default_string_config_row
    )
    assert "5 个负向契约和 2 个归一化/兼容契约" in default_string_config_row
    assert "避免默认字符串测试只证明 happy defaults" in default_string_config_row
