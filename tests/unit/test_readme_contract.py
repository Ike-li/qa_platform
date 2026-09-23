from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from qaplatform.main import create_app
from qaplatform.plugins.protocols import RunnerProtocol

ROOT = Path(__file__).resolve().parents[2]

# 英文 README 是 GitHub 首页，中文版是完整对照翻译。两份都要校验：
# 只校验一份的话，另一份的端点表与示例会在下一次改动后悄悄过期。
READMES = [
    pytest.param(
        ROOT / "README.md",
        {
            "endpoints": ("Key endpoints:", "## Common commands"),
            "plugins": ("## Plugin development", "## FAQ"),
        },
        id="en",
    ),
    pytest.param(
        ROOT / "README.zh-CN.md",
        {
            "endpoints": ("主要端点：", "## 常用命令"),
            "plugins": ("## 插件开发", "## 常见问题"),
        },
        id="zh-CN",
    ),
]


def _section(text: str, bounds: tuple[str, str]) -> str:
    start, end = bounds
    return text.split(start, 1)[1].split(end, 1)[0]


def _normalize_route(path: str) -> str:
    path_without_query = path.split("?", 1)[0]
    return re.sub(r"\{[^}]+\}", "{param}", path_without_query)


@pytest.mark.parametrize(("readme", "sections"), READMES)
def test_readme_api_endpoint_table_matches_fastapi_routes(readme, sections):
    text = readme.read_text(encoding="utf-8")
    api_section = _section(text, sections["endpoints"])
    documented = re.findall(r"`(GET|POST|PUT|PATCH|DELETE) ([^`]+)`", api_section)
    assert documented, "README API endpoint table is empty"

    # 数据源取 OpenAPI 而非 app.routes：FastAPI 0.141 起 include_router 不再把
    # 子路由展开进 app.routes，而是放一个 path 为 None 的 _IncludedRouter 包装
    # 对象，遍历顶层拿不到任何业务路由。OpenAPI 既是对外 API 的权威契约，也不
    # 依赖框架内部对象结构，不会再因升级而失效。
    spec = create_app().openapi()
    actual_routes = {
        (method.upper(), _normalize_route(path))
        for path, operations in spec["paths"].items()
        for method in operations
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }

    missing = [
        f"{method} {path}"
        for method, path in documented
        if (method, _normalize_route(path)) not in actual_routes
    ]
    assert missing == []


@pytest.mark.parametrize(("readme", "sections"), READMES)
def test_readme_runner_example_keeps_container_shell_contract_visible(readme, sections):
    text = readme.read_text(encoding="utf-8")
    plugin_section = _section(text, sections["plugins"])

    assert "import shlex" in plugin_section
    assert "cd /workspace && " in plugin_section
    assert "shlex.quote(part)" in plugin_section


def test_runner_protocol_docstring_warns_about_shell_workspace_contract():
    doc = inspect.getdoc(RunnerProtocol.build_command)

    assert doc is not None
    assert "sh -c" in doc
    assert "/workspace" in doc
    assert "quote" in doc
