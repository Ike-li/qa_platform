from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIT_TESTS = ROOT / "tests" / "unit"
INTEGRATION_TESTS = ROOT / "tests" / "integration"
E2E_TESTS = ROOT / "tests" / "e2e"
SHARED_CONFTEST = ROOT / "tests" / "conftest.py"
E2E_BACKEND_APP = ROOT / "tests" / "e2e" / "backend_app.py"
E2E_HELPERS = ROOT / "tests" / "e2e" / "helpers.ts"
OPENAPI_EXPORT = ROOT / "scripts" / "export_openapi.py"
PYTHON_TEST_ROOTS = (UNIT_TESTS, INTEGRATION_TESTS)


def _is_settings_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id == "Settings"
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == "Settings"
    return False


def _is_docstring_expr(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _json_subscript_field(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    if not isinstance(node.value, ast.Call):
        return None
    if not isinstance(node.value.func, ast.Attribute):
        return None
    if node.value.func.attr != "json":
        return None
    if not isinstance(node.slice, ast.Constant):
        return None
    if node.slice.value not in {"detail", "error"}:
        return None
    return str(node.slice.value)


def _json_alias_target(node: ast.Assign | ast.AnnAssign) -> tuple[str, str] | None:
    value = node.value
    if value is None:
        return None
    field = _json_subscript_field(value)
    if field is None:
        return None
    targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        return None
    return targets[0].id, field


def _json_alias_subfield(expression: ast.AST, aliases: dict[str, str]) -> str | None:
    if not isinstance(expression, ast.Subscript):
        return None
    if not isinstance(expression.value, ast.Name):
        return None
    field = aliases.get(expression.value.id)
    if field is None:
        return None
    if not isinstance(expression.slice, ast.Constant):
        return None
    return f"{field}.{expression.slice.value}"


def _json_nested_subfield(expression: ast.AST) -> str | None:
    if not isinstance(expression, ast.Subscript):
        return None
    field = _json_subscript_field(expression.value)
    if field is None:
        return None
    if not isinstance(expression.slice, ast.Constant):
        return None
    return f"{field}.{expression.slice.value}"


def _direct_json_error_subfield_equality(compare: ast.Compare) -> str | None:
    if not any(isinstance(op, ast.Eq) for op in compare.ops):
        return None
    for expression in [compare.left, *compare.comparators]:
        field = _json_subscript_field(expression) or _json_nested_subfield(expression)
        if field is not None:
            return field
    return None


def _aliased_json_error_subfield_equality(
    compare: ast.Compare,
    aliases: dict[str, str],
) -> str | None:
    if not any(isinstance(op, ast.Eq) for op in compare.ops):
        return None
    for expression in [compare.left, *compare.comparators]:
        field = _json_alias_subfield(expression, aliases)
        if field is not None:
            return field
    return None


def test_unit_settings_construction_does_not_read_dotenv() -> None:
    offenders: list[str] = []
    for path in [*UNIT_TESTS.rglob("*.py"), SHARED_CONFTEST]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_settings_call(node):
                continue
            if any(keyword.arg == "_env_file" for keyword in node.keywords):
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []


def test_e2e_support_settings_do_not_read_dotenv() -> None:
    tree = ast.parse(E2E_BACKEND_APP.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_settings_call(node):
            continue
        if any(keyword.arg == "_env_file" for keyword in node.keywords):
            continue
        offenders.append(f"{E2E_BACKEND_APP.relative_to(ROOT)}:{node.lineno}")

    helpers = E2E_HELPERS.read_text(encoding="utf-8")
    assert offenders == []
    assert "from qaplatform.config import Settings" not in helpers
    assert "Settings()" not in helpers


def test_openapi_export_settings_do_not_read_dotenv() -> None:
    tree = ast.parse(OPENAPI_EXPORT.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_settings_call(node):
            continue
        if any(keyword.arg == "_env_file" for keyword in node.keywords):
            continue
        offenders.append(f"{OPENAPI_EXPORT.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []


def test_python_tests_do_not_assert_error_subfields_as_whole_response() -> None:
    offenders: list[str] = []
    for root in PYTHON_TEST_ROOTS:
        for path in root.rglob("test_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for function in (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            ):
                aliases = {}
                for assign in (
                    node
                    for node in ast.walk(function)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                ):
                    alias = _json_alias_target(assign)
                    if alias is not None:
                        aliases[alias[0]] = alias[1]
                for assert_node in (
                    node for node in ast.walk(function) if isinstance(node, ast.Assert)
                ):
                    for compare in (
                        node
                        for node in ast.walk(assert_node.test)
                        if isinstance(node, ast.Compare)
                    ):
                        field = _aliased_json_error_subfield_equality(compare, aliases)
                        if field is None:
                            continue
                        offenders.append(
                            f"{path.relative_to(ROOT)}:{compare.lineno}:json_alias_subfield:{field}"
                        )
            for assert_node in (
                node for node in ast.walk(tree) if isinstance(node, ast.Assert)
            ):
                for compare in (
                    node for node in ast.walk(assert_node.test) if isinstance(node, ast.Compare)
                ):
                    field = _direct_json_error_subfield_equality(compare)
                    if field is None:
                        continue
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{compare.lineno}:json_subfield:{field}"
                    )

    assert offenders == []


def test_python_tests_do_not_use_empty_or_assert_true_bodies() -> None:
    offenders: list[str] = []
    for root in PYTHON_TEST_ROOTS:
        for path in root.rglob("test_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assert):
                    continue
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    offenders.append(f"assert_true:{path.relative_to(ROOT)}:{node.lineno}")
            for node in ast.walk(tree):
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue
                body = [item for item in node.body if not _is_docstring_expr(item)]
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    offenders.append(f"empty_test:{path.relative_to(ROOT)}:{node.lineno}")

    weak_e2e_matchers = (
        "expect.arrayContaining",
        "expect.objectContaining",
        ".toMatchObject(",
        ".toBeTruthy()",
        ".toContainText(",
    )
    for path in E2E_TESTS.glob("*.spec.ts"):
        text = path.read_text(encoding="utf-8")
        for matcher in weak_e2e_matchers:
            if matcher in text:
                offenders.append(
                    f"presence_only_e2e_matcher:{path.relative_to(ROOT)}:{matcher}"
                )

    assert offenders == []
