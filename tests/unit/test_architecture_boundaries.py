from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "qaplatform"
API_V1_ROUTE_MODULES = tuple(
    path
    for path in sorted((SRC / "api" / "v1").glob("*.py"))
    if path.name != "__init__.py"
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _calls_session_execute(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "execute":
            owner = func.value
            if isinstance(owner, ast.Name) and owner.id in {"session", "db"}:
                return True
            if isinstance(owner, ast.Attribute) and owner.attr in {"session", "db"}:
                return True
    return False


def _route_methods(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    methods: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if isinstance(func, ast.Attribute) and func.attr in {
            "post",
            "put",
            "patch",
            "delete",
        }:
            methods.add(func.attr.upper())
    return methods


def _is_audit_repository_constructor(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AuditEventRepository"
    )


def _audit_repository_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and _is_audit_repository_constructor(child.value):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(child, ast.AnnAssign) and child.value is not None:
            if _is_audit_repository_constructor(child.value) and isinstance(child.target, ast.Name):
                names.add(child.target.id)
    return names


def _is_audit_create_call(node: ast.Call, audit_repo_names: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "write_audit":
        return True
    if not isinstance(func, ast.Attribute) or func.attr != "create":
        return False

    owner = func.value
    if isinstance(owner, ast.Attribute) and owner.attr == "audit":
        return True
    if isinstance(owner, ast.Name) and owner.id in audit_repo_names:
        return True
    return _is_audit_repository_constructor(owner)


def _has_audit_write(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    audit_repo_names = _audit_repository_names(node)
    return any(
        isinstance(child, ast.Call) and _is_audit_create_call(child, audit_repo_names)
        for child in ast.walk(node)
    )


def _calls_helper(node: ast.FunctionDef | ast.AsyncFunctionDef, helper_name: str) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name) and child.func.id == helper_name:
            return True
    return False


@pytest.mark.parametrize("path", sorted((SRC / "engine").glob("*.py")))
def test_engine_layer_does_not_import_api_or_worker(path: Path):
    forbidden = {
        module
        for module in _imported_modules(path)
        if module == "qaplatform.api"
        or module.startswith("qaplatform.api.")
        or module == "qaplatform.worker"
        or module.startswith("qaplatform.worker.")
    }

    assert forbidden == set()


def test_api_metrics_reexports_observability_metric_objects():
    from qaplatform.api import metrics as api_metrics
    from qaplatform.observability import metrics as observability_metrics

    assert api_metrics.http_request_duration is observability_metrics.http_request_duration
    assert api_metrics.run_queue_depth is observability_metrics.run_queue_depth
    assert api_metrics.run_terminal_total is observability_metrics.run_terminal_total
    assert api_metrics.runs_in_flight is observability_metrics.runs_in_flight


def test_api_schemas_package_reexports_legacy_names():
    from qaplatform.api import schemas
    from qaplatform.api.schemas.analytics import TrendsResponse
    from qaplatform.api.schemas.environments import EnvironmentCreate
    from qaplatform.api.schemas.notifications import NotificationRuleCreate
    from qaplatform.api.schemas.pipelines import PipelineCreate
    from qaplatform.api.schemas.projects import ProjectCreate
    from qaplatform.api.schemas.runs import RunResponse, WebhookTriggerRequest

    assert schemas.ProjectCreate is ProjectCreate
    assert schemas.EnvironmentCreate is EnvironmentCreate
    assert schemas.PipelineCreate is PipelineCreate
    assert schemas.RunResponse is RunResponse
    assert schemas.WebhookTriggerRequest is WebhookTriggerRequest
    assert schemas.NotificationRuleCreate is NotificationRuleCreate
    assert schemas.TrendsResponse is TrendsResponse
    assert {
        "ProjectCreate",
        "EnvironmentCreate",
        "PipelineCreate",
        "RunResponse",
        "WebhookTriggerRequest",
        "NotificationRuleCreate",
        "TrendsResponse",
    } <= set(schemas.__all__)


def test_api_schemas_package_keeps_openapi_component_names():
    from qaplatform.main import create_app

    component_names = set(create_app().openapi()["components"]["schemas"])

    assert {
        "ProjectCreate",
        "EnvironmentCreate",
        "PipelineCreate",
        "RunResponse",
        "WebhookTriggerRequest",
        "NotificationRuleCreate",
        "TrendsResponse",
    } <= component_names
    assert not any("qaplatform.api.schemas" in name for name in component_names)


@pytest.mark.parametrize(
    "path",
    API_V1_ROUTE_MODULES,
)
def test_api_v1_routes_with_repository_boundaries_do_not_execute_sqlalchemy_inline(
    path: Path,
):
    assert _calls_session_execute(path) is False
    assert "sqlalchemy" not in _imported_modules(path)


@pytest.mark.parametrize(
    "path",
    [
        SRC / "api" / "auth" / "middleware.py",
        SRC / "api" / "deps.py",
    ],
)
def test_api_shared_entrypoints_with_repository_boundaries_do_not_execute_sqlalchemy_inline(
    path: Path,
):
    assert _calls_session_execute(path) is False


def test_domain_services_do_not_import_runtime_dependency_container():
    offenders = [
        path.relative_to(ROOT)
        for path in sorted((SRC / "domain").rglob("*.py"))
        if "qaplatform.dependencies" in _imported_modules(path)
    ]

    assert offenders == []


def test_api_layer_does_not_import_worker_scheduler():
    offenders = [
        path.relative_to(ROOT)
        for path in sorted((SRC / "api").rglob("*.py"))
        if "qaplatform.worker.scheduler" in _imported_modules(path)
    ]

    assert offenders == []


def test_engine_log_stream_entrypoint_is_infra_shim():
    imports = _imported_modules(SRC / "engine" / "log_stream.py")

    assert "redis.asyncio" not in imports
    assert "qaplatform.infra.log_stream" in imports


def test_mutating_api_routes_keep_audit_write_contract():
    constructor_only = ast.parse(
        """
async def route():
    audit_repo = AuditEventRepository(session)
"""
    ).body[0]
    constructor_create = ast.parse(
        """
async def route():
    audit_repo = AuditEventRepository(session)
    await audit_repo.create(action="x")
"""
    ).body[0]
    direct_create = ast.parse(
        """
async def route():
    await AuditEventRepository(session).create(action="x")
"""
    ).body[0]
    assert isinstance(constructor_only, ast.AsyncFunctionDef)
    assert isinstance(constructor_create, ast.AsyncFunctionDef)
    assert isinstance(direct_create, ast.AsyncFunctionDef)
    assert _has_audit_write(constructor_only) is False
    assert _has_audit_write(constructor_create) is True
    assert _has_audit_write(direct_create) is True

    helper_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    route_failures: list[str] = []

    for path in sorted((SRC / "api").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                helper_nodes[node.name] = node

    audited_helpers = {
        "_create_webhook_run",
        "batch_cancel_run_command",
        "batch_retry_run_command",
        "create_api_token_command",
        "create_sse_ticket_command",
        "login_user_command",
        "logout_user_command",
        "refresh_tokens_command",
        "register_user_command",
        "revoke_api_token_command",
    }
    missing_helpers = sorted(name for name in audited_helpers if name not in helper_nodes)
    assert missing_helpers == []
    for helper_name in audited_helpers:
        assert _has_audit_write(helper_nodes[helper_name])

    for path in sorted((SRC / "api").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods = _route_methods(node)
            if not methods:
                continue
            if _has_audit_write(node):
                continue
            if any(_calls_helper(node, helper_name) for helper_name in audited_helpers):
                continue

            route_failures.append(
                f"{path.relative_to(ROOT)}:{node.lineno} "
                f"{','.join(sorted(methods))} {node.name}"
            )

    assert route_failures == []


def test_direct_audit_event_writes_include_resource_id_keyword():
    failures: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "create"):
                continue

            keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
            if not {"action", "resource_type"} <= keyword_names:
                continue
            if "resource_id" in keyword_names:
                continue

            failures.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert failures == []
