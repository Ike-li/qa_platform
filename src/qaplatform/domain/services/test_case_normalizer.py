"""测试用例名规范化工具。

用于分析视图中折叠参数化用例。
"""
from __future__ import annotations


def normalize_case_name(name: str) -> str:
    """剥离参数化用例的参数段，返回母用例名。

    剥离尾部的 [...] 和 (...) 参数段。

    Args:
        name: 测试用例名（可能包含参数段）

    Returns:
        规范化后的用例名（不含参数段）

    Examples:
        >>> normalize_case_name("test_foo")
        'test_foo'
        >>> normalize_case_name("test_foo[param1]")
        'test_foo'
        >>> normalize_case_name("test_foo(param1)")
        'test_foo'
        >>> normalize_case_name("test_foo[a][b]")
        'test_foo'
        >>> normalize_case_name("test_foo[a-b-c]")
        'test_foo'
    """
    result = name

    # 从右往左找配对的括号并移除
    while True:
        stripped = False

        # 尝试移除尾部的 [...]
        if result.endswith("]"):
            depth = 0
            for i in range(len(result) - 1, -1, -1):
                if result[i] == "]":
                    depth += 1
                elif result[i] == "[":
                    depth -= 1
                    if depth == 0:
                        result = result[:i]
                        stripped = True
                        break

        # 尝试移除尾部的 (...)
        if result.endswith(")"):
            depth = 0
            for i in range(len(result) - 1, -1, -1):
                if result[i] == ")":
                    depth += 1
                elif result[i] == "(":
                    depth -= 1
                    if depth == 0:
                        result = result[:i]
                        stripped = True
                        break

        if not stripped:
            break

    return result
