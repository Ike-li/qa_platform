#!/usr/bin/env python3
"""检查 GitHub Actions workflow 里是否存在重复的 mapping 键。

YAML 允许同一层出现重复键，解析时后者静默覆盖前者。对 workflow 来说这一类
错误特别隐蔽：重复的 `on:` 会让触发条件整段失效，重复的 `steps:` 会让一半
步骤消失，而文件本身语法完全合法、Actions 也不会报错。

原先这是 tests/unit/test_release_gate_workflow.py 里的一个单测。放在测试里
不合适——它校验的是配置文件的结构合法性，属于 lint，而且那个文件同时还对
workflow 做逐字符断言，每改一次 CI 都要跟着改一次。

用法：
    python scripts/check_workflow_yaml.py [path ...]

不传路径时检查 .github/workflows/ 下所有 .yml 与 .yaml。
文件不存在时视为通过——仓库可以没有 CI 配置。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


class DuplicateKeyError(Exception):
    pass


def _construct_unique_mapping(
    loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            line = key_node.start_mark.line + 1
            raise DuplicateKeyError(f"line {line}: duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def check(path: Path) -> str | None:
    """返回错误描述，通过则返回 None。"""
    try:
        yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except DuplicateKeyError as exc:
        return f"{path}: {exc}"
    except yaml.YAMLError as exc:
        return f"{path}: invalid YAML: {exc}"
    return None


def main(argv: list[str]) -> int:
    if argv:
        targets = [Path(arg) for arg in argv]
    elif WORKFLOW_DIR.is_dir():
        targets = sorted(
            p for p in WORKFLOW_DIR.iterdir() if p.suffix in {".yml", ".yaml"}
        )
    else:
        print("no workflow directory, nothing to check")
        return 0

    errors = [msg for path in targets if (msg := check(path)) is not None]
    if errors:
        for msg in errors:
            print(f"ERROR {msg}", file=sys.stderr)
        return 1

    print(f"workflow_yaml_check=passed files={len(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
