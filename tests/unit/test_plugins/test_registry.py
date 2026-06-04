from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from qaplatform.plugins.protocols import TestResultData, TestRunResult
from qaplatform.plugins.registry import PluginRegistry


class DummyRunner:
    name = "dummy-runner"

    def build_command(self, config):
        return "run"

    async def run_tests(self, working_dir: Path, config, env_vars=None):
        return TestRunResult(1, 0, 0, 0, 1, 0)


class DummyCollector:
    name = "dummy-collector"

    async def collect(self, run_id, working_dir):
        return [TestResultData("suite", "test", "passed")]


class DummySource:
    name = "dummy-source"

    async def clone(self, url, ref, dest):
        return object()


class _EntryPoint:
    def __init__(self, name, value, loaded):
        self.name = name
        self.value = value
        self._loaded = loaded
        self.load_calls = 0

    def load(self):
        self.load_calls += 1
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


def test_register_and_retrieve_plugins_by_type():
    registry = PluginRegistry()
    runner = DummyRunner()
    collector = DummyCollector()
    source = DummySource()

    registry.register_runner(runner)
    registry.register_collector(collector)
    registry.register_source(source)

    assert registry.get_runner("dummy-runner") is runner
    assert registry.get_collector("dummy-collector") is collector
    assert registry.get_source("dummy-source") is source
    assert registry.runner_names == ["dummy-runner"]
    assert registry.collector_names == ["dummy-collector"]
    assert registry.source_names == ["dummy-source"]


@pytest.mark.parametrize(
    ("getter", "name", "message"),
    [
        ("get_runner", "missing", "Runner plugin not found"),
        ("get_collector", "missing", "Collector plugin not found"),
        ("get_source", "missing", "Source plugin not found"),
    ],
)
def test_missing_plugins_raise_actionable_key_errors(getter, name, message):
    registry = PluginRegistry()
    runner = DummyRunner()
    collector = DummyCollector()
    source = DummySource()
    registry.register_runner(runner)
    registry.register_collector(collector)
    registry.register_source(source)
    names_before = (
        registry.runner_names,
        registry.collector_names,
        registry.source_names,
    )

    with pytest.raises(KeyError) as exc_info:
        getattr(registry, getter)(name)

    assert exc_info.value.args == (f"{message}: {name}",)
    assert (
        registry.runner_names,
        registry.collector_names,
        registry.source_names,
    ) == names_before
    assert registry.get_runner("dummy-runner") is runner
    assert registry.get_collector("dummy-collector") is collector
    assert registry.get_source("dummy-source") is source


def test_auto_register_detects_runtime_protocols():
    registry = PluginRegistry()

    registry._auto_register(DummyRunner())
    registry._auto_register(DummyCollector())
    registry._auto_register(DummySource())

    assert registry.runner_names == ["dummy-runner"]
    assert registry.collector_names == ["dummy-collector"]
    assert registry.source_names == ["dummy-source"]


def test_discover_registers_loadable_entry_points_and_continues_after_failures(
    caplog,
):
    registry = PluginRegistry()
    entry_points = [
        _EntryPoint("broken", "pkg:Broken", RuntimeError("boom")),
        _EntryPoint("runner", "pkg:Runner", DummyRunner),
    ]

    with patch(
        "importlib.metadata.entry_points",
        return_value=entry_points,
    ) as entry_points_mock:
        with caplog.at_level(logging.INFO, logger="qaplatform.plugins.registry"):
            registry.discover()

    entry_points_mock.assert_called_once_with(group="qaplatform.plugins")
    assert [ep.load_calls for ep in entry_points] == [1, 1]
    assert registry.runner_names == ["dummy-runner"]
    assert registry.collector_names == []
    assert registry.source_names == []
    runner = registry.get_runner("dummy-runner")
    assert isinstance(runner, DummyRunner)
    assert runner.name == "dummy-runner"
    assert [(record.levelno, record.getMessage()) for record in caplog.records] == [
        (logging.ERROR, "failed to load plugin entry point: broken"),
        (logging.INFO, "registered runner plugin: dummy-runner"),
        (logging.INFO, "discovered external plugin: runner (pkg:Runner)"),
    ]


def test_register_builtins_includes_expected_plugin_families():
    registry = PluginRegistry()

    registry.register_builtins()

    assert registry.runner_names == ["pytest", "jest", "go_test", "playwright"]
    assert registry.collector_names == ["junit"]
    assert registry.source_names == ["git"]


def test_register_builtins_passes_git_private_host_allowlist():
    registry = PluginRegistry(git_allowed_private_hosts=["github.example"])

    registry.register_builtins()

    source = registry.get_source("git")
    assert source._allowed_private_hosts == ("github.example",)
