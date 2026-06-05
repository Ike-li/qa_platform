from __future__ import annotations

from types import SimpleNamespace

from qaplatform.engine.docker_backend import ResourceLimits
from qaplatform.engine.pipeline_config import (
    CollectorDefinition,
    PipelineConfig,
    StageDefinition,
)


def test_stage_definition_defaults_and_config_copy_behavior():
    stage = StageDefinition(name="pytest", plugin="pytest")

    assert stage.name == "pytest"
    assert stage.plugin == "pytest"
    assert stage.phase == "execute"
    assert stage.config == {}
    assert stage.continue_on_error is False


def test_collector_definition_defaults():
    collector = CollectorDefinition()

    assert collector.plugin == "junit"
    assert collector.config == {}
    assert collector.enabled is True


def test_pipeline_config_defaults():
    stages = [StageDefinition(name="pytest", plugin="pytest")]

    config = PipelineConfig(image="python:3.12", stages=stages)

    assert config.image == "python:3.12"
    assert config.stages is stages
    assert config.env_vars == {}
    assert isinstance(config.resource_limits, ResourceLimits)
    assert config.network_policy == "deny"
    assert config.timeout_seconds == 1800
    assert config.setup_script is None
    assert len(config.collectors) == 1
    assert config.collectors[0].plugin == "junit"
    assert config.source_auth is None


def test_pipeline_config_uses_explicit_collectors_and_resource_limits():
    collector = CollectorDefinition(plugin="custom", config={"path": "results.xml"})
    limits = ResourceLimits(cpu_cores=2.0)

    config = PipelineConfig(
        image="python:3.12",
        stages=[],
        env_vars={"PYTHONUNBUFFERED": "1"},
        resource_limits=limits,
        network_policy="allow",
        timeout_seconds=10,
        setup_script="pip install -r requirements.txt",
        collectors=[collector],
        source_auth={"method": "token", "secret": "redacted"},
    )

    assert config.env_vars == {"PYTHONUNBUFFERED": "1"}
    assert config.resource_limits is limits
    assert config.network_policy == "allow"
    assert config.timeout_seconds == 10
    assert config.setup_script == "pip install -r requirements.txt"
    assert config.collectors == [collector]
    assert config.source_auth == {"method": "token", "secret": "redacted"}


def test_executor_module_keeps_pipeline_config_exports():
    from qaplatform.engine import executor as executor_module

    assert executor_module.StageDefinition is StageDefinition
    assert executor_module.CollectorDefinition is CollectorDefinition
    assert executor_module.PipelineConfig is PipelineConfig


def test_pipeline_config_builder_returns_engine_config_types():
    from qaplatform.engine.pipeline_config_builder import build_pipeline_config

    pipeline = SimpleNamespace(
        stages=[{"name": "pytest", "plugin": "pytest", "config": {"k": "smoke"}}],
        collectors=[{"plugin": "junit", "config": {"path": "junit.xml"}}],
        timeout_seconds=120,
    )
    environment = SimpleNamespace(
        id="env-1",
        base_image="python:3.12",
        env_vars={"PYTHONUNBUFFERED": "1"},
        memory_mb=256,
        cpu_cores=0.5,
        resource_limits={"disk_mb": 128},
        network_policy="deny",
        setup_script=None,
    )

    config = build_pipeline_config(
        SimpleNamespace(),
        pipeline,
        environment,
        source_auth={"method": "token", "secret": "redacted"},
    )

    assert isinstance(config, PipelineConfig)
    assert isinstance(config.stages[0], StageDefinition)
    assert isinstance(config.collectors[0], CollectorDefinition)
    assert config.image == "python:3.12"
    assert config.stages[0].config == {"k": "smoke"}
    assert config.resource_limits.disk_bytes == 128 * 1024 * 1024
    assert config.source_auth == {"method": "token", "secret": "redacted"}
