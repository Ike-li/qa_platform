from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_failure_path_evidence():
    worker_encrypted_env_crypto_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Worker encrypted env_vars 缺 crypto 短路契约）"
    )
    env_vars_aad_mismatch_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Env vars AAD mismatch 解密失败契约）"
    )
    worker_max_jobs_env_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Worker max jobs env 错误契约）"
    )
    api_package_lazy_attr_row = _quality_ops_row(
        "| 2026-05-30 | N/A（API package lazy attr 错误契约）"
    )
    lifespan_init_s3_failure_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Lifespan init_s3 失败启动短路契约）"
    )
    executor_setup_clone_failure_row = _quality_ops_row(
        "| 2026-05-30 | N/A（RunExecutor setup/clone 失败短路契约）"
    )
    docker_backend_error_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Docker backend 异常传播精确契约）"
    )

    assert (
        "`tests/unit/test_worker/test_tasks.py::test_build_pipeline_config_requires_crypto_for_encrypted_env_vars` 1 passed"
        in (worker_encrypted_env_crypto_row)
    )
    assert (
        "encrypted env_vars 缺 crypto 用例从 raises-only 补成 no-PipelineConfig 契约"
        in (worker_encrypted_env_crypto_row)
    )
    assert "只证明会抛 `RuntimeError`" in worker_encrypted_env_crypto_row
    assert "把加密 envelope 当普通 env_vars 继续构造 `PipelineConfig`" in (
        worker_encrypted_env_crypto_row
    )
    assert "`PipelineConfig` 不被构造" in worker_encrypted_env_crypto_row
    assert (
        "`API_TOKEN`、`secret-value` 或 ciphertext" in worker_encrypted_env_crypto_row
    )
    assert "worker 环境变量加密测试只为异常覆盖率服务" in (
        worker_encrypted_env_crypto_row
    )

    assert (
        "`tests/unit/test_services/test_env_vars_crypto.py::test_env_vars_aad_mismatch_fails` 1 passed"
        in (env_vars_aad_mismatch_row)
    )
    assert "AAD mismatch 用例从 raises-only 补成 InvalidTag 与不泄密契约" in (
        env_vars_aad_mismatch_row
    )
    assert "只证明会抛统一 `ValueError`" in env_vars_aad_mismatch_row
    assert "错误环境 ID 的密文按普通 payload 处理" in env_vars_aad_mismatch_row
    assert "底层 cause 为 `InvalidTag`" in env_vars_aad_mismatch_row
    assert "`TOKEN`、`secret`、ciphertext 或 wrong environment_id" in (
        env_vars_aad_mismatch_row
    )
    assert "env_vars crypto 安全测试只为异常覆盖率服务" in (env_vars_aad_mismatch_row)

    assert (
        "`tests/unit/test_worker/test_settings_tasks.py::test_get_worker_max_jobs_rejects_invalid_values` 3 passed"
        in (worker_max_jobs_env_row)
    )
    assert (
        "worker max jobs 非法值用例从 raises-only 补成 exact args 与不回显原始值契约"
        in (worker_max_jobs_env_row)
    )
    assert "只匹配错误片段" in worker_max_jobs_env_row
    assert "错误配置项名漂移" in worker_max_jobs_env_row
    assert "把原始 env 值写进异常" in worker_max_jobs_env_row
    assert "`ValueError.args` 精确等于 `QAP_WORKER_MAX_JOBS must be ...`" in (
        worker_max_jobs_env_row
    )
    assert "不包含 `0`、`-1`、`many`" in worker_max_jobs_env_row
    assert "worker 并发配置测试只为异常覆盖率服务" in worker_max_jobs_env_row

    assert (
        "`tests/unit/test_api/test_api_package.py::test_api_package_unknown_attribute_raises_attribute_error` 1 passed"
        in (api_package_lazy_attr_row)
    )
    assert (
        "API package unknown attr 用例从 raises-only 补成 exact AttributeError 与 lazy export 保持契约"
        in (api_package_lazy_attr_row)
    )
    assert "只匹配 `missing`" in api_package_lazy_attr_row
    assert "模块名/属性名错误" in api_package_lazy_attr_row
    assert "miss 后污染 `create_app` lazy export" in api_package_lazy_attr_row
    assert (
        "`AttributeError.args` 精确为 `module 'qaplatform.api' has no attribute 'missing'`"
        in (api_package_lazy_attr_row)
    )
    assert "`api.create_app` 仍指向真实 `qaplatform.main.create_app`" in (
        api_package_lazy_attr_row
    )
    assert "API package 测试只为异常覆盖率服务" in api_package_lazy_attr_row

    assert (
        "`tests/unit/test_lifespan.py::TestLifespanInitializesS3::test_init_s3_failure_propagates` 1 passed"
        in (lifespan_init_s3_failure_row)
    )
    assert "lifespan init_s3 失败用例从 raises-only 补成启动短路和半初始化状态契约" in (
        lifespan_init_s3_failure_row
    )
    assert "只证明异常会冒泡" in lifespan_init_s3_failure_row
    assert "仍继续 init_crypto、注册插件、初始化 infra tracing" in (
        lifespan_init_s3_failure_row
    )
    assert "半初始化 container 放进 `app.state`" in lifespan_init_s3_failure_row
    assert "`init_crypto`、`_ensure_plugin_registry` 均未调用" in (
        lifespan_init_s3_failure_row
    )
    assert "`setup_tracing` 只发生在 create_app 构造阶段" in (
        lifespan_init_s3_failure_row
    )
    assert "`instrument_infra` 未调用" in lifespan_init_s3_failure_row
    assert "`app.state.container` 不存在" in lifespan_init_s3_failure_row
    assert "lifespan 启动失败测试只为异常覆盖率服务" in (lifespan_init_s3_failure_row)

    assert (
        "`tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_nonzero_exit_raises tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_timeout_raises tests/unit/test_engine/test_executor.py::TestExecutorUsesSourcePlugin::test_clone_repo_propagates_error` 3 passed"
        in (executor_setup_clone_failure_row)
    )
    assert (
        "executor setup/clone 失败用例从 raises-only 补成 cleanup、active execution reset 和 repository 零写入契约"
        in (executor_setup_clone_failure_row)
    )
    assert "只匹配 `Setup script failed/timed out`" in executor_setup_clone_failure_row
    assert "漏 cleanup、active execution id 残留" in executor_setup_clone_failure_row
    assert "wait timeout 使用错误" in executor_setup_clone_failure_row
    assert "只匹配 `git clone failed`" in executor_setup_clone_failure_row
    assert "失败后仍 update git_sha/commit" in executor_setup_clone_failure_row
    assert "exact RuntimeError args、create/start/wait/cleanup 参数" in (
        executor_setup_clone_failure_row
    )
    assert "`update_git_sha/commit` 不被 await" in executor_setup_clone_failure_row
    assert "executor 失败路径测试只为异常覆盖率服务" in (
        executor_setup_clone_failure_row
    )

    assert (
        "`tests/unit/test_engine/test_docker_backend.py::TestDockerBackend::test_network_mode_unknown_raises tests/unit/test_engine/test_docker_backend.py::TestDockerBackend::test_cancel_reraises_unexpected_docker_error tests/unit/test_engine/test_docker_backend.py::TestDockerBackend::test_cleanup_reraises_unexpected_docker_error` 3 passed"
        in (docker_backend_error_row)
    )
    assert (
        "Docker backend 三条异常用例从 raises-only 补成 exact network policy 与原 DockerError 透传契约"
        in (docker_backend_error_row)
    )
    assert "unknown network policy 只匹配错误片段" in docker_backend_error_row
    assert "错误默认到 bridge/none" in docker_backend_error_row
    assert "只匹配 `daemon exploded`" in docker_backend_error_row
    assert "重包装异常" in docker_backend_error_row
    assert "对错误 container id 调 kill/delete" in docker_backend_error_row
    assert "`ValueError.args` 精确包含 `unknown`" in docker_backend_error_row
    assert "透传同一个 DockerError 对象" in docker_backend_error_row
    assert '`container("container-id")`、`kill(SIGTERM)`、`delete(force=True)`' in (
        docker_backend_error_row
    )
    assert "Docker backend 异常测试只为异常覆盖率服务" in docker_backend_error_row
