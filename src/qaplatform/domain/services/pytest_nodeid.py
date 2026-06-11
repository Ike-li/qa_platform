"""pytest nodeid 重构工具。

从 (suite, name) 对重构出 pytest nodeid，用于失败子集重跑。
suite 字段存储的是 JUnit classname（如 tests.unit.test_x 或 tests.unit.test_x.TestClass）。
"""
from __future__ import annotations


def reconstruct_nodeid(suite: str, name: str) -> str:
    """从 (suite, name) 重构 pytest nodeid。

    Args:
        suite: JUnit classname，dotted path 格式（如 "tests.unit.test_x" 或 "tests.unit.test_x.TestClass"）
        name: 测试用例名（如 "test_foo" 或 "test_foo[param]"）

    Returns:
        pytest nodeid（如 "tests/unit/test_x.py::test_foo" 或 "tests/unit/test_x.py::TestClass::test_foo"）

    Examples:
        >>> reconstruct_nodeid("tests.unit.test_x", "test_foo")
        'tests/unit/test_x.py::test_foo'
        >>> reconstruct_nodeid("tests.unit.test_x.TestClass", "test_method")
        'tests/unit/test_x.py::TestClass::test_method'
        >>> reconstruct_nodeid("tests.integration.test_api", "test_create[valid]")
        'tests/integration/test_api.py::test_create[valid]'
    """
    parts = suite.split(".")

    # 从后往前找测试文件（通常是 test_ 开头）
    module_idx = -1
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].startswith("test_") or parts[i] == "test":
            module_idx = i
            break

    # 如果没找到 test_ 模块，退化到旧逻辑（末段大写判定）
    if module_idx == -1:
        if parts and parts[-1] and parts[-1][0].isupper():
            class_name = parts[-1]
            module_parts = parts[:-1]
            file_path = "/".join(module_parts) + ".py"
            return f"{file_path}::{class_name}::{name}"
        else:
            file_path = "/".join(parts) + ".py"
            return f"{file_path}::{name}"

    # 找到测试文件，分割路径和类名
    module_parts = parts[:module_idx + 1]
    class_parts = parts[module_idx + 1:]

    file_path = "/".join(module_parts) + ".py"

    if class_parts:
        # 有类名：用点号连接所有类名部分（支持嵌套类）
        class_name = ".".join(class_parts)
        return f"{file_path}::{class_name}::{name}"
    else:
        # 无类名
        return f"{file_path}::{name}"
