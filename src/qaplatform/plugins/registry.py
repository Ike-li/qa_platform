from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

from qaplatform.plugins.protocols import (
    CollectorProtocol,
    RunnerProtocol,
    SourceProtocol,
)

log = logging.getLogger(__name__)


class PluginRegistry:
    """Plugin registry: register, discover, and retrieve plugins by name.

    Built-in plugins are registered at startup. External plugins are discovered
    via the ``qaplatform.plugins`` entry-point group.
    """

    def __init__(self) -> None:
        self._runners: dict[str, RunnerProtocol] = {}
        self._collectors: dict[str, CollectorProtocol] = {}
        self._sources: dict[str, SourceProtocol] = {}

    # -- registration ---------------------------------------------------------

    def register_runner(self, plugin: RunnerProtocol) -> None:
        self._runners[plugin.name] = plugin
        log.info("registered runner plugin: %s", plugin.name)

    def register_collector(self, plugin: CollectorProtocol) -> None:
        self._collectors[plugin.name] = plugin
        log.info("registered collector plugin: %s", plugin.name)

    def register_source(self, plugin: SourceProtocol) -> None:
        self._sources[plugin.name] = plugin
        log.info("registered source plugin: %s", plugin.name)

    # -- retrieval ------------------------------------------------------------

    def get_runner(self, name: str) -> RunnerProtocol:
        try:
            return self._runners[name]
        except KeyError:
            raise KeyError(f"Runner plugin not found: {name}") from None

    def get_collector(self, name: str) -> CollectorProtocol:
        try:
            return self._collectors[name]
        except KeyError:
            raise KeyError(f"Collector plugin not found: {name}") from None

    def get_source(self, name: str) -> SourceProtocol:
        try:
            return self._sources[name]
        except KeyError:
            raise KeyError(f"Source plugin not found: {name}") from None

    # -- discovery ------------------------------------------------------------

    def discover(self) -> None:
        """Discover and register external plugins from entry points."""
        group = "qaplatform.plugins"
        for ep in importlib.metadata.entry_points(group=group):
            try:
                plugin_cls = ep.load()
                plugin = plugin_cls() if callable(plugin_cls) else plugin_cls
                self._auto_register(plugin)
                log.info("discovered external plugin: %s (%s)", ep.name, ep.value)
            except Exception:
                log.exception("failed to load plugin entry point: %s", ep.name)

    def _auto_register(self, plugin: Any) -> None:
        if isinstance(plugin, RunnerProtocol):
            self.register_runner(plugin)
        if isinstance(plugin, CollectorProtocol):
            self.register_collector(plugin)
        if isinstance(plugin, SourceProtocol):
            self.register_source(plugin)

    def register_builtins(self) -> None:
        """Register all built-in plugins."""
        from qaplatform.plugins.builtin.git_source import GitSource
        from qaplatform.plugins.builtin.go_test_runner import GoTestRunner
        from qaplatform.plugins.builtin.jest_runner import JestRunner
        from qaplatform.plugins.builtin.junit_collector import JUnitCollector
        from qaplatform.plugins.builtin.playwright_runner import PlaywrightRunner
        from qaplatform.plugins.builtin.pytest_runner import PytestRunner

        self.register_runner(PytestRunner())
        self.register_runner(JestRunner())
        self.register_runner(GoTestRunner())
        self.register_runner(PlaywrightRunner())
        self.register_collector(JUnitCollector())
        self.register_source(GitSource())

    @property
    def runner_names(self) -> list[str]:
        return list(self._runners)

    @property
    def collector_names(self) -> list[str]:
        return list(self._collectors)

    @property
    def source_names(self) -> list[str]:
        return list(self._sources)
