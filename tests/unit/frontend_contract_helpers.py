from __future__ import annotations

import re
from pathlib import Path

from qaplatform.config import Settings


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_TYPES = ROOT / "frontend" / "src" / "types" / "api.ts"
RUN_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-runs.ts"
API_TOKENS_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-api-tokens.ts"
PROJECTS_LIST_PAGE = ROOT / "frontend" / "src" / "pages" / "projects" / "list.tsx"
RUNS_LIST_PAGE = ROOT / "frontend" / "src" / "pages" / "runs" / "list.tsx"
RUN_DETAIL_PAGE = ROOT / "frontend" / "src" / "pages" / "runs" / "detail.tsx"
TEST_STATUS_ICON = ROOT / "frontend" / "src" / "components" / "test-status-icon.tsx"
TEST_RESULTS_TABLE = ROOT / "frontend" / "src" / "components" / "test-results-table.tsx"
NOTIFICATION_RULES_PANEL = ROOT / "frontend" / "src" / "components" / "projects" / "notification-rules-panel.tsx"
NOTIFICATION_RULES_HELPERS = ROOT / "frontend" / "src" / "components" / "projects" / "notification-rules" / "helpers.ts"
NOTIFICATION_RULES_RULE_FORM = ROOT / "frontend" / "src" / "components" / "projects" / "notification-rules" / "rule-form.tsx"
NOTIFICATION_RULES_CHANNEL_CONFIG = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "projects"
    / "notification-rules"
    / "channel-config-editor.tsx"
)
PIPELINE_MODAL = ROOT / "frontend" / "src" / "components" / "projects" / "pipeline-modal.tsx"
ANALYTICS_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-analytics.ts"
ANALYTICS_PANEL = ROOT / "frontend" / "src" / "components" / "projects" / "analytics-panel.tsx"
ANALYTICS_HELPERS = ROOT / "frontend" / "src" / "components" / "projects" / "analytics" / "helpers.ts"
ANALYTICS_RELEASE_SUMMARY_PANEL = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "projects"
    / "analytics"
    / "release-summary-panel.tsx"
)
ANALYTICS_TEST_HISTORY_TABLE = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "projects"
    / "analytics"
    / "test-history-table.tsx"
)
SETTINGS_PAGE = ROOT / "frontend" / "src" / "pages" / "settings.tsx"
SETTINGS_API_TOKEN_DIALOG = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "settings"
    / "api-tokens"
    / "create-api-token-dialog.tsx"
)
SETTINGS_API_TOKEN_TABLE = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "settings"
    / "api-tokens"
    / "api-token-table.tsx"
)
SETTINGS_API_TOKEN_UTILS = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "settings"
    / "api-tokens"
    / "utils.ts"
)
E2E_HELPERS = ROOT / "tests" / "e2e" / "helpers.ts"

_SCHEMA_REF_TYPE_ALIASES = {
    "CollectorDefinitionInput": "PipelineCollector",
    "NotificationChannelPayload": "NotificationChannel",
    "StageDefinitionInput": "PipelineStage",
}


def contract_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="contract-test-secret-at-least-32bytes!",
        encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        debug=True,
        environment="test",
        _env_file=None,
    )


def frontend_source() -> str:
    return FRONTEND_TYPES.read_text(encoding="utf-8")


def combined_source(*paths: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def interface_properties(interface_name: str) -> set[str]:
    return set(interface_members(interface_name))


def interface_members(interface_name: str) -> dict[str, dict[str, object]]:
    source = frontend_source()
    match = re.search(
        rf"export interface {re.escape(interface_name)}(?:<[^>]+>)?\s*\{{(?P<body>.*?)\n\}}",
        source,
        re.DOTALL,
    )
    assert match is not None, f"{interface_name} interface missing"
    members: dict[str, dict[str, object]] = {}
    for member in re.finditer(
        r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<optional>\?)?:\s*(?P<type>.*?);",
        match.group("body"),
        re.MULTILINE,
    ):
        members[member.group("name")] = {
            "optional": bool(member.group("optional")),
            "type": member.group("type").strip(),
        }
    return members


def type_aliases() -> dict[str, str]:
    source = frontend_source()
    return {
        match.group("name"): match.group("body").strip()
        for match in re.finditer(
            r"export type (?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<body>.*?);",
            source,
            re.DOTALL,
        )
    }


def literal_values(type_source: str) -> set[str]:
    aliases = type_aliases()
    values = set(re.findall(r'"([^"]+)"', type_source))
    for token in re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", type_source):
        values.update(re.findall(r'"([^"]+)"', aliases.get(token, "")))
    return values


def union_parts(type_source: str) -> set[str]:
    return {part.strip() for part in type_source.split("|")}


def ref_schema_name(schema: dict) -> str | None:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return None
    return ref.rsplit("/", 1)[-1]


def base_schema_name(schema_name: str | None) -> str | None:
    if schema_name is None:
        return None
    return re.sub(r"-(Input|Output)$", "", schema_name)


def expected_ts_ref_name(schema_name: str) -> str:
    return _SCHEMA_REF_TYPE_ALIASES.get(schema_name, schema_name)


def array_item_type(ts_type: str) -> str | None:
    match = re.fullmatch(r"(?P<item>.+)\[\]", ts_type)
    if match:
        return match.group("item").strip()
    match = re.fullmatch(r"Array<(?P<item>.+)>", ts_type)
    if match:
        return match.group("item").strip()
    return None


def non_null_schema(schema: dict) -> dict:
    for branch_key in ("anyOf", "oneOf"):
        if branch_key in schema:
            branches = [
                branch for branch in schema[branch_key]
                if branch.get("type") != "null"
            ]
            assert len(branches) == 1, f"ambiguous schema branch: {schema}"
            return branches[0]
    return schema


def schema_allows_null(schema: dict) -> bool:
    return any(
        branch.get("type") == "null"
        for branch_key in ("anyOf", "oneOf")
        for branch in schema.get(branch_key, [])
    )


def assert_frontend_type_matches_schema(field_name: str, schema: dict, ts_type: str):
    non_null = non_null_schema(schema)
    schema_type = non_null.get("type")

    if schema_allows_null(schema):
        assert "null" in ts_type, f"{field_name} can be null in OpenAPI"
    else:
        assert "null" not in union_parts(ts_type), f"{field_name} cannot be null in OpenAPI"

    if "enum" in non_null:
        expected_values = set(non_null["enum"])
        assert literal_values(ts_type) == expected_values, field_name
        assert "string" not in union_parts(ts_type), f"{field_name} is broader than OpenAPI enum"
    elif schema_type in {"integer", "number"}:
        assert "number" in ts_type, field_name
    elif schema_type == "boolean":
        assert "boolean" in ts_type, field_name
    elif schema_type == "string":
        assert "string" in ts_type or literal_values(ts_type), field_name
    elif schema_type == "array":
        _assert_array_type_matches_schema(field_name, non_null, ts_type)
    elif schema_type == "object":
        assert (
            "Record<" in ts_type
            or "unknown" in ts_type
            or re.search(r"\b[A-Z][A-Za-z0-9_]*\b", ts_type)
        ), field_name
    elif "$ref" in non_null:
        assert ts_type and ts_type != "unknown", field_name
    else:
        raise AssertionError(f"unsupported schema for {field_name}: {schema}")


def _assert_array_type_matches_schema(field_name: str, schema: dict, ts_type: str):
    item_type = array_item_type(ts_type)
    assert item_type is not None, field_name
    item_schema = schema["items"]
    item_union_refs = {
        base_schema_name(ref_schema_name(non_null_schema(branch)))
        for branch_key in ("anyOf", "oneOf")
        for branch in item_schema.get(branch_key, [])
    }
    notification_condition_union_refs = {
        frozenset(
            {
                "NotificationConditionLeaf",
                "NotificationConditionAllGroup",
                "NotificationConditionAnyGroup",
            }
        ),
        frozenset(
            {
                "NotificationConditionLeaf",
                "NotificationConditionResponseAllGroup",
                "NotificationConditionResponseAnyGroup",
                "NotificationInvalidCondition",
            }
        ),
    }
    if frozenset(item_union_refs) in notification_condition_union_refs:
        assert item_type == "NotificationConditionExpression", field_name
        return

    item_schema = non_null_schema(item_schema)
    item_ref = ref_schema_name(item_schema)
    if item_ref is not None:
        assert item_type == expected_ts_ref_name(item_ref), field_name
    elif item_schema.get("type") == "string":
        assert item_type == "string" or literal_values(item_type), field_name
    elif item_schema.get("type") in {"integer", "number"}:
        assert item_type == "number", field_name
    elif item_schema.get("type") == "boolean":
        assert item_type == "boolean", field_name
    elif item_schema.get("type") == "object":
        assert (
            item_type.startswith("Record<")
            or item_type == "unknown"
            or re.fullmatch(r"[A-Z][A-Za-z0-9_]*", item_type)
        ), field_name
    else:
        raise AssertionError(f"unsupported array item schema for {field_name}: {schema}")
