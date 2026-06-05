from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from qaplatform.engine.executor_collectors import (
    collect_from_plugin,
    collector_accepts_config,
)


class NewCollector:
    async def collect(self, run_id, working_dir, config):
        return [
            {
                "run_id": run_id,
                "working_dir": working_dir,
                "config": config,
            }
        ]


class OldCollector:
    async def collect(self, run_id, working_dir):
        return [
            {
                "run_id": run_id,
                "working_dir": working_dir,
            }
        ]


class VarargsCollector:
    async def collect(self, *args):
        return list(args)


def test_collector_accepts_config_for_new_and_varargs_collectors():
    assert collector_accepts_config(NewCollector()) is True
    assert collector_accepts_config(VarargsCollector()) is True


def test_collector_accepts_config_rejects_legacy_two_arg_collectors():
    assert collector_accepts_config(OldCollector()) is False


@pytest.mark.asyncio
async def test_collect_from_plugin_passes_config_to_new_collectors(tmp_path: Path):
    run_id = uuid4()
    config = {"path": "reports/custom.xml"}

    results = await collect_from_plugin(NewCollector(), run_id, tmp_path, config)

    assert results == [
        {
            "run_id": run_id,
            "working_dir": tmp_path,
            "config": config,
        }
    ]


@pytest.mark.asyncio
async def test_collect_from_plugin_omits_config_for_legacy_collectors(tmp_path: Path):
    run_id = uuid4()

    results = await collect_from_plugin(
        OldCollector(),
        run_id,
        tmp_path,
        {"path": "reports/custom.xml"},
    )

    assert results == [
        {
            "run_id": run_id,
            "working_dir": tmp_path,
        }
    ]


def test_executor_module_keeps_collector_helper_exports():
    import qaplatform.engine.executor as executor_module
    import qaplatform.engine.executor_collectors as collectors

    assert executor_module._collector_accepts_config is collectors.collector_accepts_config
    assert executor_module._collect_from_plugin is collectors.collect_from_plugin
