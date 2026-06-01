from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUALITY_OPS = ROOT / "docs" / "testing-quality-ops.md"


@lru_cache(maxsize=None)
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _quality_ops_row(prefix: str, *, contains: str | None = None) -> str:
    return next(
        line
        for line in _read(QUALITY_OPS).splitlines()
        if line.startswith(prefix) and (contains is None or contains in line)
    )


def _quality_ops_row_containing(*needles: str) -> str:
    for line in _read(QUALITY_OPS).splitlines():
        if all(needle in line for needle in needles):
            return line
    raise AssertionError(f"Missing quality ops row containing {needles!r}")


def _quality_ops_rows_containing(*needle_groups: str | tuple[str, ...]) -> str:
    rows = []
    for needle_group in needle_groups:
        needles = (needle_group,) if isinstance(needle_group, str) else needle_group
        rows.append(_quality_ops_row_containing(*needles))
    return "\n".join(rows)


def _after(text: str, marker: str) -> str:
    return text.split(marker, 1)[1]


def _before(text: str, marker: str) -> str:
    return text.split(marker, 1)[0]


def _block_between(text: str, start: str, end: str) -> str:
    return _before(_after(text, start), end)


def _marked_block(text: str, start: str, end: str) -> str:
    return start + _block_between(text, start, end)


def _marked_block_or_tail(text: str, start: str, end: str) -> str:
    tail = _after(text, start)
    if end in tail:
        tail = _before(tail, end)
    return start + tail


def _test_block(
    text: str,
    test_name: str,
    *,
    next_marker: str = "\n\n@pytest.mark.asyncio",
) -> str:
    return _block_between(text, f"async def {test_name}", next_marker)


def _notification_channel_sections(channels_test: str) -> dict[str, str]:
    return {
        "webhook": _marked_block(
            channels_test,
            "class TestWebhookChannel",
            "# DingtalkChannel",
        ),
        "dingtalk": _marked_block(
            channels_test,
            "class TestDingtalkChannel",
            "# WecomChannel",
        ),
        "wecom": _marked_block(
            channels_test,
            "class TestWecomChannel",
            "# ChannelRouter",
        ),
    }


def _notification_channel_http_case_blocks(channels_test: str) -> dict[str, str]:
    sections = _notification_channel_sections(channels_test)
    return {
        "webhook_method": _marked_block(
            sections["webhook"],
            "async def test_custom_method",
            "async def test_custom_headers",
        ),
        "webhook_headers": _marked_block_or_tail(
            sections["webhook"],
            "async def test_custom_headers",
            "# DingtalkChannel",
        ),
        "dingtalk_sign": _marked_block(
            sections["dingtalk"],
            "async def test_signs_request_when_secret_configured",
            "async def test_timeout_returns_failure_without_secret_values",
        ),
        "dingtalk_markdown": _marked_block(
            sections["dingtalk"],
            "async def test_markdown_message",
            "async def test_http_error_status_returns_failure",
        ),
        "wecom_markdown": _marked_block(
            sections["wecom"],
            "async def test_markdown_message",
            "async def test_http_error_status_returns_failure_without_webhook_key",
        ),
    }


def _enclosing_function_name(
    node: ast.AST, parent_by_child: dict[ast.AST, ast.AST]
) -> str | None:
    while node in parent_by_child:
        node = parent_by_child[node]
        if isinstance(node, ast.FunctionDef):
            return node.name
    return None


def _is_constant(node: ast.AST, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def _is_single_split_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "split"
        and len(node.args) == 2
        and _is_constant(node.args[1], 1)
        and not node.keywords
    )


def _is_manual_block_split_slice(node: ast.AST) -> bool:
    if not (
        isinstance(node, ast.Subscript)
        and _is_constant(node.slice, 0)
        and _is_single_split_call(node.value)
        and isinstance(node.value.func.value, ast.Subscript)
    ):
        return False
    inner = node.value.func.value
    return (
        _is_constant(inner.slice, 1)
        and isinstance(inner.value, ast.Call)
        and _is_single_split_call(inner.value)
    )


def _is_single_boundary_split_slice(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value in {0, 1}
        and _is_single_split_call(node.value)
    )


def _source_maintenance_counts(contract_source: str) -> dict[str, int]:
    contract_ast = ast.parse(contract_source)
    nodes = list(ast.walk(contract_ast))
    parent_by_child = {
        child: node
        for node in nodes
        for child in ast.iter_child_nodes(node)
    }

    def owner(node: ast.AST) -> str | None:
        return _enclosing_function_name(node, parent_by_child)

    return {
        "direct_read_calls": sum(
            1
            for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_text"
        ),
        "direct_next_calls": sum(
            1
            for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "next"
        ),
        "manual_block_split_slices": sum(
            1
            for node in nodes
            if owner(node) != "_block_between"
            and _is_manual_block_split_slice(node)
        ),
        "manual_single_split_slices": sum(
            1
            for node in nodes
            if owner(node) not in {"_after", "_before"}
            and _is_single_boundary_split_slice(node)
        ),
        "manual_index_find_calls": sum(
            1
            for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"index", "find"}
        ),
        "quality_ops_join_assignments": sum(
            1
            for node in nodes
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "quality_ops"
                for target in node.targets
            )
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "join"
            and isinstance(node.value.func.value, ast.Constant)
            and node.value.func.value.value == "\n"
        ),
        "quality_ops_read_calls": sum(
            1
            for node in nodes
            if owner(node) not in {"_quality_ops_row", "_quality_ops_row_containing"}
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_read"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "QUALITY_OPS"
        ),
    }


def _contract_maintenance_counts(*contract_sources: str) -> dict[str, int]:
    totals = {
        "direct_read_calls": 0,
        "direct_next_calls": 0,
        "manual_block_split_slices": 0,
        "manual_single_split_slices": 0,
        "manual_index_find_calls": 0,
        "quality_ops_join_assignments": 0,
        "quality_ops_read_calls": 0,
    }
    for contract_source in contract_sources:
        for key, value in _source_maintenance_counts(contract_source).items():
            totals[key] += value
    return totals
