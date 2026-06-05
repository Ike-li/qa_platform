"""Build execution pipeline configuration from ORM-like records."""

from __future__ import annotations

from qaplatform.domain.services.env_vars_crypto import (
    decrypt_env_vars,
    is_encrypted_env_vars,
)
from qaplatform.engine.docker_backend import ResourceLimits
from qaplatform.engine.pipeline_config import (
    CollectorDefinition,
    PipelineConfig,
    StageDefinition,
)


def build_pipeline_config(
    run,
    pipeline_orm,
    environment_orm,
    crypto=None,
    source_auth: dict[str, str] | None = None,
) -> PipelineConfig:
    stages = [
        StageDefinition(
            name=stage_dict.get("name", "stage"),
            plugin=stage_dict.get("plugin", "pytest"),
            phase=stage_dict.get("phase", "execute"),
            config=stage_dict.get("config", {}),
            continue_on_error=stage_dict.get("continue_on_error", False),
        )
        for stage_dict in pipeline_orm.stages
    ]

    raw_env_vars = environment_orm.env_vars or {}
    if is_encrypted_env_vars(raw_env_vars):
        if crypto is None:
            raise RuntimeError("Crypto service not initialised")
        env_vars = decrypt_env_vars(
            raw_env_vars,
            environment_id=environment_orm.id,
            crypto=crypto,
        )
    else:
        env_vars = dict(raw_env_vars)

    raw_resource_limits = environment_orm.resource_limits or {}
    max_artifact_size_mb = raw_resource_limits.get("max_artifact_size_mb", 100)
    max_artifacts_count = raw_resource_limits.get("max_artifacts_count", 50)
    disk_mb = raw_resource_limits.get("disk_mb")
    disk_bytes = disk_mb * 1024 * 1024 if disk_mb else None

    raw_collectors = getattr(pipeline_orm, "collectors", None)
    if not isinstance(raw_collectors, list) or not raw_collectors:
        raw_collectors = [{"plugin": "junit", "config": {}, "enabled": True}]
    collectors = [
        CollectorDefinition(
            plugin=collector.get("plugin", "junit"),
            config=collector.get("config") or {},
            enabled=collector.get("enabled", True),
        )
        for collector in raw_collectors
        if isinstance(collector, dict)
    ] or [CollectorDefinition()]

    return PipelineConfig(
        image=environment_orm.base_image,
        stages=stages,
        env_vars=env_vars,
        resource_limits=ResourceLimits(
            memory_bytes=environment_orm.memory_mb * 1024 * 1024,
            cpu_cores=environment_orm.cpu_cores,
            disk_bytes=disk_bytes,
            max_artifact_size_bytes=max_artifact_size_mb * 1024 * 1024,
            max_artifacts_count=max_artifacts_count,
        ),
        network_policy=environment_orm.network_policy,
        timeout_seconds=pipeline_orm.timeout_seconds or 1800,
        setup_script=environment_orm.setup_script,
        collectors=collectors,
        source_auth=source_auth,
    )
