"""Collector invocation compatibility helpers."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from uuid import UUID


def collector_accepts_config(collector: Any) -> bool:
    try:
        signature = inspect.signature(collector.collect)
    except (TypeError, ValueError):
        return True

    params = list(signature.parameters.values())
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return True
    positional = [
        p
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    # Bound methods expose run_id, working_dir, config as three positional
    # parameters. Older collectors only expose run_id and working_dir.
    return len(positional) >= 3


async def collect_from_plugin(
    collector: Any,
    run_id: UUID,
    working_dir: Path,
    config: dict[str, Any],
) -> list[Any]:
    if collector_accepts_config(collector):
        return await collector.collect(run_id, working_dir, config)
    return await collector.collect(run_id, working_dir)
