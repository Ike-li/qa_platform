"""Execution pipeline configuration objects."""

from __future__ import annotations

from typing import Any

from qaplatform.engine.docker_backend import ResourceLimits


class StageDefinition:
    """Represents a single stage in a pipeline."""

    def __init__(
        self,
        name: str,
        plugin: str,
        phase: str = "execute",
        config: dict[str, Any] | None = None,
        continue_on_error: bool = False,
    ) -> None:
        self.name = name
        self.plugin = plugin
        self.phase = phase
        self.config = config or {}
        self.continue_on_error = continue_on_error


class CollectorDefinition:
    """Represents a result collector plugin configured for a pipeline."""

    def __init__(
        self,
        plugin: str = "junit",
        config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> None:
        self.plugin = plugin
        self.config = config or {}
        self.enabled = enabled


class PipelineConfig:
    """Pipeline configuration for an execution run."""

    def __init__(
        self,
        image: str,
        stages: list[StageDefinition],
        env_vars: dict[str, str] | None = None,
        resource_limits: ResourceLimits | None = None,
        network_policy: str = "deny",
        timeout_seconds: int = 1800,
        setup_script: str | None = None,
        collectors: list[CollectorDefinition] | None = None,
        source_auth: dict[str, str] | None = None,
    ) -> None:
        self.image = image
        self.stages = stages
        self.env_vars = env_vars or {}
        self.resource_limits = resource_limits or ResourceLimits()
        self.network_policy = network_policy
        self.timeout_seconds = timeout_seconds
        self.setup_script = setup_script
        self.collectors = collectors if collectors is not None else [CollectorDefinition()]
        self.source_auth = source_auth
