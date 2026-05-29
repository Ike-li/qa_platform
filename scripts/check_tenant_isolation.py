#!/usr/bin/env python3
"""CI guard for direct queries on run-scoped tables without tenant context.

Artifact, test_result, and run_event rows do not carry tenant_id directly.
Read/write access must either join through Run or stay inside a narrowly
allowed run-scoped repository helper whose callers already checked the Run.
"""

from __future__ import annotations

import argparse
import ast
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SRC = Path(__file__).resolve().parent.parent / "src" / "qaplatform"

TARGET_MODELS = frozenset({"Artifact", "TestResult", "RunEvent"})
RUN_MODELS = frozenset({"Run"})
MODEL_IMPORT_MODULE = "qaplatform.infra.database.models"
SQLA_CALLS = frozenset({"select", "update", "delete", "sa_delete"})
RUN_SCOPE_ATTRS = frozenset({"tenant_id", "project_id"})
TARGET_REPO_ATTRS = frozenset({"artifact", "test_result", "run_event"})
GENERIC_REPO_READ_METHODS = frozenset({"get_by_id", "list"})

ALLOWLIST = frozenset({
    (
        "src/qaplatform/infra/database/repositories/run_repo.py",
        "TestResultRepository",
        "list_by_run",
    ),
    (
        "src/qaplatform/infra/database/repositories/run_repo.py",
        "TestResultRepository",
        "list_by_run_and_status",
    ),
    (
        "src/qaplatform/infra/database/repositories/run_repo.py",
        "ArtifactRepository",
        "list_by_run",
    ),
})


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    models: tuple[str, ...]
    context: str


@dataclass(frozen=True)
class QueryInfo:
    models: frozenset[str]
    has_run_relation: bool
    has_run_scope: bool
    context: str
    line: int

    @property
    def target_models(self) -> tuple[str, ...]:
        return tuple(sorted(self.models & TARGET_MODELS))

    @property
    def has_safe_run_context(self) -> bool:
        return self.has_run_relation and self.has_run_scope


@dataclass(frozen=True)
class RunGuard:
    var_name: str
    line: int
    arg_name: str | None = None
    target_var: str | None = None


class TenantIsolationVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        tree: ast.AST,
        source: str,
        path: str,
        model_aliases: dict[str, str],
        module_aliases: set[str],
    ) -> None:
        self.tree = tree
        self.source = source
        self.path = path
        self.model_aliases = model_aliases
        self.module_aliases = module_aliases
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.violations: list[Violation] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.function_stack:
            return
        self._check_statement(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.function_stack:
            return
        self._check_statement(node)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        self._check_statement(node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self._check_statement(node)
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self._check_repository_calls(node)
        self._check_body(node.body, query_vars={}, scope_vars=set())
        self.function_stack.pop()

    def _check_statement(self, node: ast.stmt) -> None:
        info = _query_info_from_expr(
            node,
            query_vars={},
            scope_vars=set(),
            source=self.source,
            model_aliases=self.model_aliases,
            module_aliases=self.module_aliases,
        )
        if info is None:
            return
        self._record_query_violation(info)

    def _check_body(
        self,
        body: list[ast.stmt],
        *,
        query_vars: dict[str, QueryInfo],
        scope_vars: set[str],
    ) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(stmt)
                continue

            if isinstance(stmt, ast.Assign):
                info = _query_info_from_expr(
                    stmt.value,
                    query_vars=query_vars,
                    scope_vars=scope_vars,
                    source=self.source,
                    model_aliases=self.model_aliases,
                    module_aliases=self.module_aliases,
                )
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if info is not None:
                            query_vars[target.id] = info
                        elif _has_run_scope(
                            stmt.value,
                            model_aliases=self.model_aliases,
                            module_aliases=self.module_aliases,
                        ):
                            scope_vars.add(target.id)
                self._check_execute_calls(stmt, query_vars)
                continue

            if isinstance(stmt, ast.AnnAssign):
                info = _query_info_from_expr(
                    stmt.value,
                    query_vars=query_vars,
                    scope_vars=scope_vars,
                    source=self.source,
                    model_aliases=self.model_aliases,
                    module_aliases=self.module_aliases,
                ) if stmt.value is not None else None
                if isinstance(stmt.target, ast.Name):
                    if info is not None:
                        query_vars[stmt.target.id] = info
                    elif stmt.value is not None and _has_run_scope(
                        stmt.value,
                        model_aliases=self.model_aliases,
                        module_aliases=self.module_aliases,
                    ):
                        scope_vars.add(stmt.target.id)
                self._check_execute_calls(stmt, query_vars)
                continue

            self._check_execute_calls(stmt, query_vars)
            if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
                for nested in _nested_bodies(stmt):
                    self._check_body(
                        nested,
                        query_vars=dict(query_vars),
                        scope_vars=set(scope_vars),
                    )

    def _check_execute_calls(
        self,
        stmt: ast.stmt,
        query_vars: dict[str, QueryInfo],
    ) -> None:
        for call in (node for node in ast.walk(stmt) if isinstance(node, ast.Call)):
            if _call_name(call.func) != "execute" or not call.args:
                continue
            info = _query_info_from_expr(
                call.args[0],
                query_vars=query_vars,
                scope_vars=set(),
                source=self.source,
                model_aliases=self.model_aliases,
                module_aliases=self.module_aliases,
            )
            if info is not None:
                self._record_query_violation(info)

    def _check_repository_calls(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
            repo_call = _target_generic_repo_call(call)
            if repo_call is None:
                continue
            repo_attr, method = repo_call
            if _target_generic_repo_call_is_guarded(node, call, method):
                continue
            context = ast.get_source_segment(self.source, call) or ""
            self.violations.append(
                Violation(
                    path=self.path,
                    line=getattr(call, "lineno", 0),
                    models=(repo_attr,),
                    context=(
                        f"generic repos.{repo_attr}.{method} without repos.run.get_for_tenant guard: "
                        + " ".join(context.split())
                    ),
                )
            )

    def _record_query_violation(self, info: QueryInfo) -> None:
        targets = info.target_models
        if not targets:
            return
        if info.has_safe_run_context:
            return
        if self._is_allowlisted():
            return
        self.violations.append(
            Violation(
                path=self.path,
                line=info.line,
                models=targets,
                context=info.context,
            )
        )

    def _is_allowlisted(self) -> bool:
        current_class = self.class_stack[-1] if self.class_stack else ""
        current_function = self.function_stack[-1] if self.function_stack else ""
        return (self.path, current_class, current_function) in ALLOWLIST


def _collect_model_aliases(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    model_aliases: dict[str, str] = {}
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == MODEL_IMPORT_MODULE:
            for alias in node.names:
                if alias.name in TARGET_MODELS | RUN_MODELS:
                    model_aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == MODEL_IMPORT_MODULE:
                    module_aliases.add(alias.asname or alias.name.rsplit(".", 1)[-1])
    return model_aliases, module_aliases


def _contains_sqlalchemy_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = _call_name(child.func)
        if name in SQLA_CALLS:
            return True
    return False


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _query_info_from_expr(
    node: ast.AST | None,
    *,
    query_vars: dict[str, QueryInfo],
    scope_vars: set[str],
    source: str,
    model_aliases: dict[str, str],
    module_aliases: set[str],
) -> QueryInfo | None:
    if node is None:
        return None
    referenced_query_vars = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and child.id in query_vars
    }
    if not _contains_sqlalchemy_call(node) and not referenced_query_vars:
        return None

    models = _referenced_models(
        node,
        model_aliases=model_aliases,
        module_aliases=module_aliases,
    )
    has_run_relation = _has_run_relation(
        node,
        model_aliases=model_aliases,
        module_aliases=module_aliases,
    )
    has_run_scope = _has_run_scope(
        node,
        model_aliases=model_aliases,
        module_aliases=module_aliases,
    ) or _uses_scope_var(node, scope_vars)
    context = ast.get_source_segment(source, node) or ""
    line = getattr(node, "lineno", 0)

    for name in referenced_query_vars:
        previous = query_vars[name]
        models |= set(previous.models)
        has_run_relation = has_run_relation or previous.has_run_relation
        has_run_scope = has_run_scope or previous.has_run_scope
        if not context:
            context = previous.context
        if not line:
            line = previous.line

    return QueryInfo(
        models=frozenset(models),
        has_run_relation=has_run_relation,
        has_run_scope=has_run_scope,
        context=" ".join(context.split()),
        line=line,
    )


def _has_run_relation(
    node: ast.AST,
    *,
    model_aliases: dict[str, str],
    module_aliases: set[str],
) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Compare):
            continue
        operands = [child.left, *child.comparators]
        attrs = [
            _model_attr(operand, model_aliases=model_aliases, module_aliases=module_aliases)
            for operand in operands
        ]
        for left in attrs:
            for right in attrs:
                if left is None or right is None:
                    continue
                if left[0] in RUN_MODELS and left[1] == "id" and right[0] in TARGET_MODELS and right[1] == "run_id":
                    return True
                if right[0] in RUN_MODELS and right[1] == "id" and left[0] in TARGET_MODELS and left[1] == "run_id":
                    return True
    return False


def _has_run_scope(
    node: ast.AST,
    *,
    model_aliases: dict[str, str],
    module_aliases: set[str],
) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Compare):
            continue
        operands = [child.left, *child.comparators]
        for index, op in enumerate(child.ops):
            if not isinstance(op, ast.Eq):
                continue
            left = operands[index]
            right = operands[index + 1]
            left_attr = _model_attr(
                left,
                model_aliases=model_aliases,
                module_aliases=module_aliases,
            )
            right_attr = _model_attr(
                right,
                model_aliases=model_aliases,
                module_aliases=module_aliases,
            )
            if _is_run_scope_attr(left_attr) and _is_isolation_value(right, right_attr):
                return True
            if _is_run_scope_attr(right_attr) and _is_isolation_value(left, left_attr):
                return True
    return False


def _is_run_scope_attr(attr: tuple[str, str] | None) -> bool:
    return attr is not None and attr[0] in RUN_MODELS and attr[1] in RUN_SCOPE_ATTRS


def _is_isolation_value(node: ast.AST, attr: tuple[str, str] | None) -> bool:
    if isinstance(node, ast.Constant) and node.value is None:
        return False
    if _is_run_scope_attr(attr):
        return False
    return isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript))


def _uses_scope_var(node: ast.AST, scope_vars: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in scope_vars:
            return True
        if isinstance(child, ast.Starred) and isinstance(child.value, ast.Name) and child.value.id in scope_vars:
            return True
    return False


def _model_attr(
    node: ast.AST,
    *,
    model_aliases: dict[str, str],
    module_aliases: set[str],
) -> tuple[str, str] | None:
    if not isinstance(node, ast.Attribute):
        return None
    if isinstance(node.value, ast.Name):
        model = model_aliases.get(node.value.id)
        if model:
            return model, node.attr
        if node.value.id in module_aliases and node.attr in TARGET_MODELS | RUN_MODELS:
            return node.attr, ""
    if isinstance(node.value, ast.Attribute):
        parent = _model_attr(
            node.value,
            model_aliases=model_aliases,
            module_aliases=module_aliases,
        )
        if parent is not None and parent[0] in TARGET_MODELS | RUN_MODELS:
            return parent[0], node.attr
    return None


def _nested_bodies(node: ast.stmt) -> list[list[ast.stmt]]:
    bodies: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        value = getattr(node, attr, None)
        if isinstance(value, list):
            bodies.append(value)
    handlers = getattr(node, "handlers", None)
    if handlers:
        bodies.extend(handler.body for handler in handlers)
    return bodies


def _target_generic_repo_call(node: ast.Call) -> tuple[str, str] | None:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in GENERIC_REPO_READ_METHODS:
        return None
    repo = func.value
    if not isinstance(repo, ast.Attribute):
        return None
    if repo.attr not in TARGET_REPO_ATTRS:
        return None
    if isinstance(repo.value, ast.Name) and repo.value.id == "repos":
        return repo.attr, func.attr
    return None


def _target_generic_repo_call_is_guarded(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    call: ast.Call,
    method: str,
) -> bool:
    if method == "get_by_id":
        target_var = _assignment_target_for_call(function, call)
        if target_var is None:
            return False
        return _has_run_guard_for_target_var(function, target_var, after_line=call.lineno)
    if method == "list":
        guarded_names = _run_guard_names_before(function, before_line=call.lineno)
        if not guarded_names:
            return False
        return _list_call_has_guarded_run_filter(function, call, guarded_names)
    return False


def _assignment_target_for_call(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    call: ast.Call,
) -> str | None:
    for stmt in ast.walk(function):
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        value = stmt.value
        if value is None or not _contains_node(value, call):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in targets:
            if isinstance(target, ast.Name):
                return target.id
    return None


def _contains_node(root: ast.AST, needle: ast.AST) -> bool:
    return any(node is needle for node in ast.walk(root))


def _has_run_guard_for_target_var(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    target_var: str,
    *,
    after_line: int,
) -> bool:
    for guard in _run_guard_assignments(function):
        if guard.line <= after_line or guard.target_var != target_var:
            continue
        if _guard_var_checked(function, guard.var_name, after_line=guard.line):
            return True
    return False


def _run_guard_names_before(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    before_line: int,
) -> set[str]:
    guarded: set[str] = set()
    for guard in _run_guard_assignments(function):
        if guard.line >= before_line or guard.arg_name is None:
            continue
        if _guard_var_checked(function, guard.var_name, after_line=guard.line, before_line=before_line):
            guarded.add(guard.arg_name)
    return guarded


def _run_guard_assignments(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[RunGuard]:
    guards: list[RunGuard] = []
    for stmt in ast.walk(function):
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        value = stmt.value
        if value is None:
            continue
        call = _run_guard_call_from_expr(value)
        if call is None or not call.args:
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        guard_var = next((target.id for target in targets if isinstance(target, ast.Name)), None)
        if guard_var is None:
            continue
        first_arg = call.args[0]
        arg_name = first_arg.id if isinstance(first_arg, ast.Name) else None
        target_var = (
            first_arg.value.id
            if (
                isinstance(first_arg, ast.Attribute)
                and first_arg.attr == "run_id"
                and isinstance(first_arg.value, ast.Name)
            )
            else None
        )
        guards.append(
            RunGuard(
                var_name=guard_var,
                line=getattr(stmt, "lineno", getattr(call, "lineno", 0)),
                arg_name=arg_name,
                target_var=target_var,
            )
        )
    return guards


def _run_guard_call_from_expr(node: ast.AST) -> ast.Call | None:
    for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
        func = call.func
        if not isinstance(func, ast.Attribute) or func.attr != "get_for_tenant":
            continue
        repo = func.value
        if (
            isinstance(repo, ast.Attribute)
            and repo.attr == "run"
            and isinstance(repo.value, ast.Name)
            and repo.value.id == "repos"
        ):
            return call
    return None


def _guard_var_checked(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    guard_var: str,
    *,
    after_line: int,
    before_line: int | None = None,
) -> bool:
    upper = before_line if before_line is not None else 10**9
    for stmt in function.body:
        line = getattr(stmt, "lineno", 0)
        if line <= after_line:
            continue
        if line >= upper:
            return False
        if isinstance(stmt, (ast.Return, ast.Raise)):
            return False
        if not isinstance(stmt, ast.If):
            continue
        if _condition_checks_guard_none(stmt.test, guard_var) and _body_terminates(stmt.body):
            return True
    return False


def _condition_checks_guard_none(node: ast.AST, guard_var: str) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return isinstance(node.operand, ast.Name) and node.operand.id == guard_var
    if not isinstance(node, ast.Compare):
        return False
    operands = [node.left, *node.comparators]
    for index, op in enumerate(node.ops):
        if not isinstance(op, (ast.Is, ast.Eq)):
            continue
        left = operands[index]
        right = operands[index + 1]
        if _is_name(left, guard_var) and _is_none_literal(right):
            return True
        if _is_none_literal(left) and _is_name(right, guard_var):
            return True
    return False


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_none_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _body_terminates(body: list[ast.stmt]) -> bool:
    for stmt in reversed(body):
        if isinstance(stmt, ast.Pass):
            continue
        return isinstance(stmt, (ast.Return, ast.Raise))
    return False


def _list_call_has_guarded_run_filter(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    call: ast.Call,
    guarded_names: set[str],
) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "filters":
            continue
        if _expr_has_target_run_id_filter(keyword.value, guarded_names):
            return True
        if isinstance(keyword.value, ast.Name):
            filters_var = keyword.value.id
            if _filter_var_has_guarded_run_id(function, filters_var, call.lineno, guarded_names):
                return True
    return False


def _filter_var_has_guarded_run_id(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    filters_var: str,
    before_line: int,
    guarded_names: set[str],
) -> bool:
    for stmt in ast.walk(function):
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        if getattr(stmt, "lineno", 0) >= before_line:
            continue
        value = stmt.value
        if value is None:
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        if not any(isinstance(target, ast.Name) and target.id == filters_var for target in targets):
            continue
        if _expr_has_target_run_id_filter(value, guarded_names):
            return True
    return False


def _expr_has_target_run_id_filter(node: ast.AST, guarded_names: set[str]) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Compare):
            continue
        operands = [child.left, *child.comparators]
        has_target_run_id = any(_is_target_run_id_attr(operand) for operand in operands)
        has_guarded_name = any(
            isinstance(operand, ast.Name) and operand.id in guarded_names
            for operand in operands
        )
        if has_target_run_id and has_guarded_name:
            return True
    return False


def _is_target_run_id_attr(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "run_id"
        and isinstance(node.value, ast.Name)
        and (
            node.value.id in TARGET_MODELS
            or node.value.id.endswith("ORM")
            or node.value.id.endswith("Model")
        )
    )


def _referenced_models(
    node: ast.AST,
    *,
    model_aliases: dict[str, str],
    module_aliases: set[str],
) -> set[str]:
    models: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            model = model_aliases.get(child.id)
            if model:
                models.add(model)
        elif isinstance(child, ast.Attribute):
            if isinstance(child.value, ast.Name):
                if child.value.id in module_aliases and child.attr in TARGET_MODELS | RUN_MODELS:
                    models.add(child.attr)
                model = model_aliases.get(child.value.id)
                if model:
                    models.add(model)
    return models


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path(__file__).resolve().parent.parent).as_posix()
    except ValueError:
        return path.as_posix()


def scan_text(source: str, *, path: str = "<memory>") -> list[Violation]:
    tree = ast.parse(source, filename=path)
    model_aliases, module_aliases = _collect_model_aliases(tree)
    visitor = TenantIsolationVisitor(
        tree=tree,
        source=source,
        path=path,
        model_aliases=model_aliases,
        module_aliases=module_aliases,
    )
    visitor.visit(tree)
    return visitor.violations


def scan_paths(paths: Iterable[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for py in paths:
        source = py.read_text(encoding="utf-8")
        violations.extend(scan_text(source, path=_display_path(py)))
    return violations


def run_self_tests() -> None:
    cases = [
        (
            "direct select without Run join fails",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact

            async def load(session, artifact_id):
                stmt = (
                    select(Artifact)
                    .where(Artifact.id == artifact_id)
                )
                return await session.execute(stmt)
            """,
            True,
            "<direct-select>",
        ),
        (
            "direct aliased select without Run join fails",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact as ArtifactORM

            async def load(session, artifact_id):
                stmt = select(ArtifactORM.storage_path).where(
                    ArtifactORM.id == artifact_id
                )
                return await session.execute(stmt)
            """,
            True,
            "<direct-aliased-select>",
        ),
        (
            "join through Run passes",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact, Run

            async def load(session, tenant_id):
                stmt = (
                    select(Artifact)
                    .join(Run, Run.id == Artifact.run_id)
                    .where(Run.tenant_id == tenant_id)
                )
                return await session.execute(stmt)
            """,
            False,
            "<run-join>",
        ),
        (
            "Run reference without join fails",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact, Run

            async def load(session, tenant_id):
                stmt = (
                    select(Artifact)
                    .where(Run.tenant_id == tenant_id)
                )
                return await session.execute(stmt)
            """,
            True,
            "<run-reference-without-join>",
        ),
        (
            "Run join without tenant or project scope fails",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact, Run

            async def load(session):
                stmt = (
                    select(Artifact)
                    .join(Run, Run.id == Artifact.run_id)
                )
                return await session.execute(stmt)
            """,
            True,
            "<run-join-without-scope>",
        ),
        (
            "Run scope selected but not filtered fails",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact, Run

            async def load(session):
                stmt = (
                    select(Artifact, Run.tenant_id)
                    .join(Run, Run.id == Artifact.run_id)
                )
                return await session.execute(stmt)
            """,
            True,
            "<run-scope-selected-not-filtered>",
        ),
        (
            "Run scope existence check fails",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact, Run

            async def load(session):
                stmt = (
                    select(Artifact)
                    .join(Run, Run.id == Artifact.run_id)
                    .where(Run.tenant_id != None)
                )
                return await session.execute(stmt)
            """,
            True,
            "<run-scope-existence-check>",
        ),
        (
            "Run scope self compare fails",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact, Run

            async def load(session):
                stmt = (
                    select(Artifact)
                    .join(Run, Run.id == Artifact.run_id)
                    .where(Run.tenant_id == Run.tenant_id)
                )
                return await session.execute(stmt)
            """,
            True,
            "<run-scope-self-compare>",
        ),
        (
            "split safe query construction passes",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Artifact, Run

            async def load(session, tenant_id):
                stmt = select(Artifact)
                stmt = stmt.join(Run, Run.id == Artifact.run_id)
                stmt = stmt.where(Run.tenant_id == tenant_id)
                return await session.execute(stmt)
            """,
            False,
            "<split-safe-query>",
        ),
        (
            "aliased analytics join through Run passes",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import Run as RunORM
            from qaplatform.infra.database.models import TestResult as TestResultORM

            async def load(session, project_id):
                filters = (RunORM.project_id == project_id,)
                stmt = (
                    select(TestResultORM.suite, TestResultORM.name)
                    .join(RunORM, RunORM.id == TestResultORM.run_id)
                    .where(*filters)
                )
                return await session.execute(stmt)
            """,
            False,
            "<aliased-run-join>",
        ),
        (
            "run-scoped repository helper passes by allowlist",
            """
            from sqlalchemy import select
            from qaplatform.infra.database.models import TestResult

            class TestResultRepository:
                async def list_by_run(self, run_id):
                    stmt = (
                        select(TestResult)
                        .where(TestResult.run_id == run_id)
                    )
            """,
            False,
            "src/qaplatform/infra/database/repositories/run_repo.py",
        ),
        (
            "generic target repository read without run guard fails",
            """
            async def load(repos, artifact_id):
                return await repos.artifact.get_by_id(artifact_id)
            """,
            True,
            "<unguarded-repo-read>",
        ),
        (
            "unrelated run guard does not protect artifact read",
            """
            async def load(repos, artifact_id, unrelated_run_id, tenant_id):
                await repos.run.get_for_tenant(unrelated_run_id, tenant_id)
                return await repos.artifact.get_by_id(artifact_id)
            """,
            True,
            "<unrelated-run-guard>",
        ),
        (
            "one guarded read does not protect a second artifact read",
            """
            async def load(repos, first_artifact_id, second_artifact_id, tenant_id):
                first = await repos.artifact.get_by_id(first_artifact_id)
                await repos.run.get_for_tenant(first.run_id, tenant_id)
                return await repos.artifact.get_by_id(second_artifact_id)
            """,
            True,
            "<one-guard-two-reads>",
        ),
        (
            "generic target repository read with run guard passes",
            """
            async def load(repos, artifact_id, tenant_id):
                artifact = await repos.artifact.get_by_id(artifact_id)
                run = await repos.run.get_for_tenant(artifact.run_id, tenant_id)
                if run is None:
                    return None
                return artifact, run
            """,
            False,
            "<guarded-repo-read>",
        ),
        (
            "generic target list with guarded run filter passes",
            """
            from qaplatform.infra.database.models import TestResult as TestResultORM

            async def load(repos, run_id, tenant_id):
                run = await repos.run.get_for_tenant(run_id, tenant_id)
                if run is None:
                    return None
                filters = [TestResultORM.run_id == run_id]
                return await repos.test_result.list(filters=filters)
            """,
            False,
            "<guarded-repo-list>",
        ),
        (
            "unchecked generic repository guard fails",
            """
            async def load(repos, artifact_id, tenant_id):
                artifact = await repos.artifact.get_by_id(artifact_id)
                await repos.run.get_for_tenant(artifact.run_id, tenant_id)
                return artifact
            """,
            True,
            "<unchecked-repo-guard>",
        ),
        (
            "non-terminating guard none check fails",
            """
            async def load(repos, artifact_id, tenant_id):
                artifact = await repos.artifact.get_by_id(artifact_id)
                run = await repos.run.get_for_tenant(artifact.run_id, tenant_id)
                if run is None:
                    pass
                return artifact
            """,
            True,
            "<non-terminating-guard-check>",
        ),
        (
            "nested return in guard none check fails",
            """
            async def load(repos, artifact_id, tenant_id, flag):
                artifact = await repos.artifact.get_by_id(artifact_id)
                run = await repos.run.get_for_tenant(artifact.run_id, tenant_id)
                if run is None:
                    if flag:
                        return None
                    pass
                return artifact
            """,
            True,
            "<nested-return-guard-check>",
        ),
        (
            "nested helper return in guard none check fails",
            """
            async def load(repos, artifact_id, tenant_id):
                artifact = await repos.artifact.get_by_id(artifact_id)
                run = await repos.run.get_for_tenant(artifact.run_id, tenant_id)
                if run is None:
                    def helper():
                        return None
                    helper()
                return artifact
            """,
            True,
            "<nested-helper-return-guard-check>",
        ),
        (
            "dead-code guard none check fails",
            """
            async def load(repos, artifact_id, tenant_id):
                artifact = await repos.artifact.get_by_id(artifact_id)
                run = await repos.run.get_for_tenant(artifact.run_id, tenant_id)
                return artifact
                if run is None:
                    return None
            """,
            True,
            "<dead-code-guard-check>",
        ),
        (
            "nested function guard none check fails",
            """
            async def load(repos, artifact_id, tenant_id):
                artifact = await repos.artifact.get_by_id(artifact_id)
                run = await repos.run.get_for_tenant(artifact.run_id, tenant_id)
                def guard_helper():
                    if run is None:
                        return None
                return artifact
            """,
            True,
            "<nested-function-guard-check>",
        ),
    ]
    for name, source, expect_violation, path in cases:
        violations = scan_text(textwrap.dedent(source), path=path)
        if bool(violations) != expect_violation:
            raise AssertionError(f"{name}: expected violation={expect_violation}, got {violations}")
    print("§3.2 SELF-TEST OK: tenant isolation audit detects direct queries and allows Run joins")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run built-in parser checks before scanning source",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        run_self_tests()

    violations = scan_paths(SRC.rglob("*.py"))
    if violations:
        print("§3.2 VIOLATION: direct query on run-scoped table without Run tenant context:")
        for violation in violations:
            models = ",".join(violation.models)
            print(f"  {violation.path}:{violation.line}:{models} -> {violation.context}")
        return 1

    print("§3.2 OK: no unsafe direct Artifact/TestResult/RunEvent queries without Run context")
    return 0


if __name__ == "__main__":
    sys.exit(main())
