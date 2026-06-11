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

    # 末段判定：以大写字母开头视为类名
    if parts and parts[-1] and parts[-1][0].isupper():
        # 有类名：倒数第二段是模块
        class_name = parts[-1]
        module_parts = parts[:-1]
        file_path = "/".join(module_parts) + ".py"
        return f"{file_path}::{class_name}::{name}"
    else:
        # 无类名：全段视为模块路径
        file_path = "/".join(parts) + ".py"
        return f"{file_path}::{name}"
