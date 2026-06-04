from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PREVIEW = ROOT / "frontend" / "src" / "components" / "runs" / "artifact-preview.tsx"
RUN_DETAIL_PAGE = ROOT / "frontend" / "src" / "pages" / "runs" / "detail.tsx"
USE_AUTH = ROOT / "frontend" / "src" / "hooks" / "use-auth.tsx"
API_CLIENT = ROOT / "frontend" / "src" / "lib" / "api.ts"
REAL_LOGIN_FLOW = ROOT / "tests" / "e2e" / "real-login-flow.spec.ts"
E2E_HELPERS = ROOT / "tests" / "e2e" / "helpers.ts"
TRIGGER_RUN_MODAL = (
    ROOT / "frontend" / "src" / "components" / "runs" / "trigger-run-modal.tsx"
)


def test_artifact_preview_iframe_keeps_report_origin_sandboxed():
    source = ARTIFACT_PREVIEW.read_text(encoding="utf-8")

    assert 'sandbox="allow-scripts"' in source
    assert "allow-same-origin" not in source
    assert 'referrerPolicy="no-referrer"' in source


def test_artifact_preview_and_download_reject_non_http_urls_before_opening():
    source = RUN_DETAIL_PAGE.read_text(encoding="utf-8")

    assert "function isSafeArtifactUrl(url: string): boolean" in source
    assert 'parsed.protocol === "https:" || parsed.protocol === "http:"' in source
    assert source.count("if (!isSafeArtifactUrl(url))") == 3

    preview_handler = source.split("aria-label={t('runs.artifacts.previewArtifact'", 1)[
        1
    ].split("<Download", 1)[0]
    download_handler = source.split("aria-label={t('runs.artifacts.downloadArtifact'", 1)[
        1
    ].split("</Button>", 1)[0]

    assert "if (!isSafeArtifactUrl(url))" in preview_handler
    assert preview_handler.index("if (!isSafeArtifactUrl(url))") < preview_handler.index(
        "setPreview({"
    )
    assert "if (!isSafeArtifactUrl(url))" in download_handler
    assert download_handler.index("if (!isSafeArtifactUrl(url))") < download_handler.index(
        'window.open(url, "_blank", "noopener,noreferrer")'
    )


def test_initial_auth_refresh_failure_does_not_clear_successful_login_token():
    source = USE_AUTH.read_text(encoding="utf-8")
    init_auth = source.split("const initAuth = async () => {", 1)[1].split(
        "initAuth();",
        1,
    )[0]

    assert "getAccessToken" in source
    assert "if (getAccessToken() === null)" in init_auth
    assert init_auth.index("if (getAccessToken() === null)") < init_auth.rindex(
        "setIsLoading(false);"
    )
    assert "setIsAuthenticated(false);" in init_auth


def test_login_page_skips_initial_refresh_that_can_clear_new_cookie():
    source = USE_AUTH.read_text(encoding="utf-8")
    init_auth = source.split("const initAuth = async () => {", 1)[1].split(
        "initAuth();",
        1,
    )[0]

    assert 'window.location.pathname === "/login"' in init_auth
    assert "return;" in init_auth.split('window.location.pathname === "/login"', 1)[1]
    assert init_auth.index('window.location.pathname === "/login"') < init_auth.index(
        "refreshAccessToken();"
    )


def test_refresh_helper_uses_configured_api_client_base_url():
    source = API_CLIENT.read_text(encoding="utf-8")
    refresh_body = source.split("export function refreshAccessToken", 1)[1].split(
        "const AUTH_PATHS",
        1,
    )[0]

    expected = (
        'refreshPromise = api\n'
        '      .post("/auth/refresh", null, { withCredentials: true })'
    )
    assert expected in refresh_body
    assert '"/api/v1/auth/refresh"' not in refresh_body
    assert "refreshPromise = axios" not in refresh_body


def test_login_success_finishes_auth_loading_before_protected_navigation():
    source = USE_AUTH.read_text(encoding="utf-8")
    login_body = source.split("const login = (access_token: string) => {", 1)[1].split(
        "};",
        1,
    )[0]

    assert "setAccessToken(access_token);" in login_body
    assert "setIsAuthenticated(true);" in login_body
    assert "setIsLoading(false);" in login_body
    assert login_body.index("setAccessToken(access_token);") < login_body.index(
        "setIsLoading(false);"
    )


def test_ui_login_helper_waits_for_authenticated_shell_before_returning():
    source = E2E_HELPERS.read_text(encoding="utf-8")
    helper = source.split("export async function loginViaUi", 1)[1].split(
        "export async function loginViaApi",
        1,
    )[0]

    assert "toHaveURL(/\\/projects$/)" in helper
    assert 'getByRole("heading", { name: "Projects", exact: true })' in helper
    assert 'getByRole("button", { name: /Log out/i })' in helper
    assert helper.index("toHaveURL(/\\/projects$/)") < helper.index(
        'getByRole("button", { name: /Log out/i })'
    )


def test_trigger_run_selects_remain_controlled_before_data_loads():
    source = TRIGGER_RUN_MODAL.read_text(encoding="utf-8")

    assert "const selectedPipelineId = watchPipelineId ?? defaultPipelineId ?? \"\";" in (
        source
    )
    assert "const selectedEnvironmentId = watch(\"environment_id\") ?? DEFAULT_ENVIRONMENT;" in (
        source
    )
    assert "const selectedPriority = String(watch(\"priority\") ?? 1);" in source
    assert "value={selectedPipelineId}" in source
    assert "value={watchPipelineId || defaultPipelineId}" not in source
    assert "reset({ pipeline_id: defaultPipelineId ?? \"\", priority: 1 })" in source


def test_real_login_flow_searches_created_project_before_opening_it():
    source = REAL_LOGIN_FLOW.read_text(encoding="utf-8")

    assert 'getByRole("textbox", { name: "Search projects..." }).fill(project.name)' in (
        source
    )
    assert source.index('fill(project.name)') < source.index(
        'locator(`a[href="/projects/${project.id}"]`)'
    )
