import { expect, test } from "@playwright/test";
import {
  authHeaders,
  createActiveWebhookRunViaDb,
  createRunWithArchivedEvidenceViaDb,
  createProject,
  createRunWithResultsViaDb,
  createTenantUserViaDb,
  ensureEnvironment,
  ensurePipeline,
  expectApiOk,
  loginViaApi,
  loginViaUi,
  uniqueSuffix,
  updateProject,
  type Paginated,
} from "./helpers";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

test.describe("special regression coverage against the real app", () => {
  test.describe.configure({ mode: "serial" });

  test("project settings validates and persists silent windows from the UI", async ({ page, request }) => {
    const suffix = uniqueSuffix();
    const { token } = await loginViaApi(request);
    const project = await createProject(request, token, {
      name: `E2E Silent ${suffix}`,
      slug: `e2e-silent-${suffix}`,
    });

    await loginViaUi(page);
    await page.goto(`/projects/${project.id}`);
    await expect(page.getByRole("heading", { level: 1, name: project.name })).toBeVisible();
    await page.getByRole("tab", { name: /Settings/ }).click();
    await page.getByRole("button", { name: "Add Window" }).click();

    await page.locator('input[id^="silent_start_"]').last().fill("2026-06-01T10:00");
    await page.locator('input[id^="silent_end_"]').last().fill("2026-06-01T09:00");
    await page.locator('input[id^="silent_reason_"]').last().fill(`Release freeze ${suffix}`);
    await page.getByRole("button", { name: "Save Changes" }).last().click();
    await expect(page.getByText("End time must be later than start time.")).toBeVisible();

    await page.locator('input[id^="silent_end_"]').last().fill("2026-06-01T11:00");
    await page.getByRole("button", { name: "Save Changes" }).last().click();
    await expect(page.getByText("Silent windows saved")).toBeVisible();

    const response = await request.get(`/api/v1/projects/${project.id}`, {
      headers: authHeaders(token),
    });
    await expectApiOk(response, "Read project after saving silent windows");
    const refreshed = await response.json();
    const savedWindow = refreshed.silent_windows[0];
    expect(savedWindow.start_at).toMatch(/(Z|[+-]\d\d:\d\d)$/);
    expect(savedWindow.end_at).toMatch(/(Z|[+-]\d\d:\d\d)$/);
    expect(refreshed.silent_windows).toEqual([
      {
        start_at: savedWindow.start_at,
        end_at: savedWindow.end_at,
        reason: `Release freeze ${suffix}`,
      },
    ]);
  });

  test("environment variable values are masked in the project environment UI", async ({ page, request }) => {
    const suffix = uniqueSuffix();
    const secret = `secret-${suffix}`;
    const { token } = await loginViaApi(request);
    const project = await createProject(request, token, {
      name: `E2E Env ${suffix}`,
      slug: `e2e-env-${suffix}`,
    });
    await ensureEnvironment(request, token, project.id, {
      name: `Masked Env ${suffix}`,
      env_vars: { API_TOKEN: secret },
    });
    await ensureEnvironment(request, token, project.id, {
      name: `Decoy Env ${suffix}`,
      env_vars: { DECOY_TOKEN: `decoy-secret-${suffix}` },
    });

    await loginViaUi(page);
    await page.goto(`/projects/${project.id}`);
    await expect(page.getByRole("heading", { level: 1, name: project.name })).toBeVisible();
    await page.getByRole("tab", { name: /Environments/ }).click();

    await expect(page.getByRole("region", { name: `Decoy Env ${suffix} environment` })).toBeVisible();
    const environmentCard = page.getByRole("region", { name: `Masked Env ${suffix} environment` });
    await expect(environmentCard).toBeVisible();
    await expect(environmentCard.getByRole("heading", { name: `Masked Env ${suffix}` })).toBeVisible();
    await expect(environmentCard.locator('input[placeholder="KEY"]')).toHaveCount(1);
    await expect(environmentCard.locator('input[placeholder="KEY"]')).toHaveValue("API_TOKEN");
    await expect(environmentCard.getByText(secret)).toHaveCount(0);

    const valueInput = environmentCard.locator('input[placeholder="VALUE"]');
    await expect(valueInput).toHaveCount(1);
    await expect(valueInput).toHaveAttribute("type", "password");
    await environmentCard.getByRole("button", { name: "Show value" }).click();
    await expect(valueInput).toHaveAttribute("type", "text");
    await expect(valueInput).toHaveValue(secret);
  });

  test("notification rule cards do not render DingTalk or WeCom secrets", async ({ page, request }) => {
    const suffix = uniqueSuffix();
    const dingtalkToken = `dt-token-${suffix}`;
    const dingtalkSecret = `dt-secret-${suffix}`;
    const wecomKey = `wecom-key-${suffix}`;
    const { token } = await loginViaApi(request);
    const project = await createProject(request, token, {
      name: `E2E Notify ${suffix}`,
      slug: `e2e-notify-${suffix}`,
    });

    const createRule = await request.post(`/api/v1/projects/${project.id}/notification-rules`, {
      headers: authHeaders(token),
      data: {
        name: `Secret channels ${suffix}`,
        enabled: true,
        conditions: [],
        channels: [
          {
            type: "dingtalk",
            config: { access_token: dingtalkToken, secret: dingtalkSecret, msgtype: "text" },
          },
          {
            type: "wecom",
            config: { webhook_key: wecomKey, msgtype: "markdown" },
          },
        ],
        template: "Run {{run_id}} finished with {{status}}",
      },
    });
    await expectApiOk(createRule, "Create secret-channel notification rule");

    await loginViaUi(page);
    await page.goto(`/projects/${project.id}`);
    await expect(page.getByRole("heading", { level: 1, name: project.name })).toBeVisible();
    await page.getByRole("tab", { name: /Notifications/ }).click();

    await expect(page.getByText(`Secret channels ${suffix}`)).toBeVisible();
    await expect(page.getByText("dingtalk")).toBeVisible();
    await expect(page.getByText("wecom")).toBeVisible();
    await expect(page.getByText(dingtalkToken)).toHaveCount(0);
    await expect(page.getByText(dingtalkSecret)).toHaveCount(0);
    await expect(page.getByText(wecomKey)).toHaveCount(0);
  });

  test("webhook branch filtering and same-commit deduplication stay observable end-to-end", async ({ page, request }) => {
    const suffix = uniqueSuffix();
    const allowedBranch = `e2e-main-${suffix}`;
    const filteredBranch = `e2e-blocked-${suffix}`;
    const gitSha = `sha-${suffix}`;
    const login = await loginViaApi(request);
    const project = await createProject(request, login.token, {
      name: `E2E Webhook ${suffix}`,
      slug: `e2e-webhook-${suffix}`,
    });
    const environment = await ensureEnvironment(request, login.token, project.id);
    const pipeline = await ensurePipeline(request, login.token, project.id, {
      command: "python -c 'import time; time.sleep(30)'",
    });
    await updateProject(request, login.token, project.id, {
      settings: { allowed_branches: [allowedBranch] },
    });

    const filtered = await request.post(`/api/v1/webhooks/${project.id}/trigger`, {
      headers: authHeaders(login.token),
      data: {
        git_ref: `refs/heads/${filteredBranch}`,
        git_sha: `filtered-${suffix}`,
        metadata: { provider: "playwright-e2e" },
      },
    });
    expect(filtered.status()).toBe(200);
    expect(await filtered.json()).toEqual({
      status: "filtered",
      reason: "branch_not_allowed",
    });

    const dedupKey = `playwright-e2e:${project.git_url}:${gitSha}:${allowedBranch}`;
    const activeRun = createActiveWebhookRunViaDb({
      tenantId: project.tenant_id,
      userId: login.user.id,
      projectId: project.id,
      pipelineId: pipeline.id,
      environmentId: environment.id,
      branch: allowedBranch,
      gitSha,
      dedupKey,
    });

    const duplicate = await request.post(`/api/v1/webhooks/${project.id}/trigger`, {
      headers: authHeaders(login.token),
      data: {
        git_ref: `refs/heads/${allowedBranch}`,
        git_sha: gitSha,
        metadata: { provider: "playwright-e2e" },
      },
    });
    expect(duplicate.status()).toBe(200);
    expect(await duplicate.json()).toEqual({ status: "duplicate" });

    const runsResponse = await request.get(`/api/v1/runs?project_id=${project.id}&per_page=100`, {
      headers: authHeaders(login.token),
    });
    await expectApiOk(runsResponse, "List runs after webhook deduplication");
    const runs = (await runsResponse.json()) as Paginated<{
      id: string;
      project_id: string;
      pipeline_id: string;
      pipeline_name: string;
      environment_id: string;
      status: string;
      trigger_type: string;
      git_sha: string | null;
      git_ref: string;
      attempt: number;
    }> & { page: number; per_page: number };
    expect({
      page: runs.page,
      per_page: runs.per_page,
      total: runs.total,
      data: runs.data.map((run) => ({
        id: run.id,
        project_id: run.project_id,
        pipeline_id: run.pipeline_id,
        pipeline_name: run.pipeline_name,
        environment_id: run.environment_id,
        status: run.status,
        trigger_type: run.trigger_type,
        git_sha: run.git_sha,
        git_ref: run.git_ref,
        attempt: run.attempt,
      })),
    }).toEqual({
      page: 1,
      per_page: 100,
      total: 1,
      data: [
        {
          id: activeRun.id,
          project_id: project.id,
          pipeline_id: pipeline.id,
          pipeline_name: pipeline.name,
          environment_id: environment.id,
          status: "queued",
          trigger_type: "webhook",
          git_sha: gitSha,
          git_ref: `refs/heads/${allowedBranch}`,
          attempt: 1,
        },
      ],
    });

    await loginViaUi(page);
    await page.goto("/runs");
    await expect(page.getByText(allowedBranch)).toBeVisible();
    await expect(page.getByText(filteredBranch)).toHaveCount(0);
  });

  test("audit event access keeps owner visibility and member denial", async ({ request }) => {
    const suffix = uniqueSuffix();
    const ownerLogin = await loginViaApi(request);
    const project = await createProject(request, ownerLogin.token, {
      name: `E2E Audit ${suffix}`,
      slug: `e2e-audit-${suffix}`,
    });

    const ownerAudit = await request.get(
      `/api/v1/audit-events?action=project.create&resource_type=project&resource_id=${project.id}&per_page=10`,
      { headers: authHeaders(ownerLogin.token) },
    );
    expect(ownerAudit.status()).toBe(200);
    const ownerAuditBody = (await ownerAudit.json()) as Paginated<{
      id: string;
      tenant_id: string;
      user_id: string;
      action: string;
      resource_type: string;
      resource_id: string;
      before_state: Record<string, unknown> | null;
      after_state: Record<string, unknown>;
      ip_address: string | null;
      user_agent: string | null;
      created_at: string;
    }> & { page: number; per_page: number };
    const projectCreateAudit = ownerAuditBody.data[0];
    expect(projectCreateAudit.id).toMatch(UUID_PATTERN);
    expect(projectCreateAudit.created_at).toMatch(/(Z|[+-]\d\d:\d\d)$/);
    expect(projectCreateAudit.after_state.created_at).toMatch(/(Z|[+-]\d\d:\d\d)$/);
    expect(projectCreateAudit.after_state.updated_at).toMatch(/(Z|[+-]\d\d:\d\d)$/);
    expect({
      page: ownerAuditBody.page,
      per_page: ownerAuditBody.per_page,
      total: ownerAuditBody.total,
      data: [
        {
          ...projectCreateAudit,
          id: "<uuid>",
          created_at: "<timestamp>",
          after_state: {
            ...projectCreateAudit.after_state,
            created_at: "<timestamp>",
            updated_at: "<timestamp>",
          },
        },
      ],
    }).toEqual({
      page: 1,
      per_page: 10,
      total: 1,
      data: [
        {
          id: "<uuid>",
          tenant_id: ownerLogin.user.tenant_id,
          user_id: ownerLogin.user.id,
          action: "project.create",
          resource_type: "project",
          resource_id: project.id,
          before_state: null,
          after_state: {
            id: project.id,
            tenant_id: ownerLogin.user.tenant_id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            git_url: project.git_url,
            git_auth_method: "none",
            credential_id: null,
            default_branch: "main",
            root_path: ".",
            shallow_clone: true,
            default_env_id: null,
            settings: {},
            silent_windows: [],
            status: "active",
            created_by: ownerLogin.user.id,
            created_at: "<timestamp>",
            updated_at: "<timestamp>",
          },
          ip_address: null,
          user_agent: null,
          created_at: "<timestamp>",
        },
      ],
    });

    const memberPassword = `member-pass-${suffix}`;
    const member = createTenantUserViaDb({
      tenantId: ownerLogin.user.tenant_id,
      username: `member_${suffix.replace(/-/g, "_")}`,
      email: `member-${suffix}@e2e.local`,
      password: memberPassword,
      role: "member",
    });
    expect(member.id).toMatch(UUID_PATTERN);

    const memberLogin = await loginViaApi(request, {
      username: `member_${suffix.replace(/-/g, "_")}`,
      password: memberPassword,
      tenantId: ownerLogin.user.tenant_id,
    });
    const memberAudit = await request.get("/api/v1/audit-events", {
      headers: authHeaders(memberLogin.token),
    });
    expect(memberAudit.status()).toBe(403);
    await expect(memberAudit.json()).resolves.toEqual({ detail: "Insufficient permissions" });
  });

  test("run result API filters remain consistent with run detail data", async ({ page, request }) => {
    const suffix = uniqueSuffix();
    const ownerLogin = await loginViaApi(request);
    const project = await createProject(request, ownerLogin.token, {
      name: `E2E Results ${suffix}`,
      slug: `e2e-results-${suffix}`,
    });
    const environment = await ensureEnvironment(request, ownerLogin.token, project.id);
    const pipeline = await ensurePipeline(request, ownerLogin.token, project.id);
    const run = createRunWithResultsViaDb({
      tenantId: ownerLogin.user.tenant_id,
      userId: ownerLogin.user.id,
      projectId: project.id,
      pipelineId: pipeline.id,
      environmentId: environment.id,
      branch: `results-${suffix}`,
      gitSha: `results-sha-${suffix}`,
      results: [
        { suite: "checkout", name: `test_checkout_ok_${suffix}`, status: "passed" },
        {
          suite: "checkout",
          name: `test_checkout_timeout_${suffix}`,
          status: "failed",
          error_message: `timeout-${suffix}`,
        },
        { suite: "billing", name: `test_billing_skipped_${suffix}`, status: "skipped" },
      ],
    });

    const failedResponse = await request.get(`/api/v1/runs/${run.id}/results?status=failed`, {
      headers: authHeaders(ownerLogin.token),
    });
    expect(failedResponse.status()).toBe(200);
    type TestResultPage = Paginated<{
      id: string;
      run_id: string;
      suite: string;
      name: string;
      status: string;
      duration_ms: number;
      error_message: string | null;
      stack_trace: string | null;
      tags: string[];
      metadata: Record<string, unknown>;
    }> & { page: number; per_page: number };
    const normalizeResultPage = (body: TestResultPage) => ({
      ...body,
      data: body.data.map((result) => {
        expect(result.id).toMatch(UUID_PATTERN);
        return { ...result, id: "<uuid>" };
      }),
    });

    const failedBody = (await failedResponse.json()) as TestResultPage;
    const expectedFailedResult = {
      id: "<uuid>",
      run_id: run.id,
      suite: "checkout",
      name: `test_checkout_timeout_${suffix}`,
      status: "failed",
      duration_ms: 1,
      error_message: `timeout-${suffix}`,
      stack_trace: null,
      tags: [],
      metadata: {},
    };
    expect(normalizeResultPage(failedBody)).toEqual({
      data: [expectedFailedResult],
      page: 1,
      per_page: 20,
      total: 1,
    });

    const suiteResponse = await request.get(`/api/v1/runs/${run.id}/results?suite=billing`, {
      headers: authHeaders(ownerLogin.token),
    });
    expect(suiteResponse.status()).toBe(200);
    const suiteBody = (await suiteResponse.json()) as TestResultPage;
    expect(normalizeResultPage(suiteBody)).toEqual({
      data: [
        {
          id: "<uuid>",
          run_id: run.id,
          suite: "billing",
          name: `test_billing_skipped_${suffix}`,
          status: "skipped",
          duration_ms: 1,
          error_message: null,
          stack_trace: null,
          tags: [],
          metadata: {},
        },
      ],
      page: 1,
      per_page: 20,
      total: 1,
    });

    const queryResponse = await request.get(`/api/v1/runs/${run.id}/results?q=timeout-${suffix}`, {
      headers: authHeaders(ownerLogin.token),
    });
    expect(queryResponse.status()).toBe(200);
    const queryBody = (await queryResponse.json()) as TestResultPage;
    expect(normalizeResultPage(queryBody)).toEqual({
      data: [expectedFailedResult],
      page: 1,
      per_page: 20,
      total: 1,
    });

    await loginViaUi(page);
    await page.goto(`/runs/${run.id}`);
    await expect(page.getByText(`test_checkout_ok_${suffix}`)).toBeVisible();
    await expect(page.getByText(`test_checkout_timeout_${suffix}`)).toBeVisible();
    await expect(page.getByText(`test_billing_skipped_${suffix}`)).toBeVisible();
  });

  test("run detail replays archived logs and previews stored artifacts", async ({ page, request }) => {
    const suffix = uniqueSuffix();
    const ownerLogin = await loginViaApi(request);
    const project = await createProject(request, ownerLogin.token, {
      name: `E2E Evidence ${suffix}`,
      slug: `e2e-evidence-${suffix}`,
    });
    const environment = await ensureEnvironment(request, ownerLogin.token, project.id);
    const pipeline = await ensurePipeline(request, ownerLogin.token, project.id);
    const artifactName = `allure-report/index-${suffix}.html`;
    const run = createRunWithArchivedEvidenceViaDb({
      tenantId: ownerLogin.user.tenant_id,
      userId: ownerLogin.user.id,
      projectId: project.id,
      pipelineId: pipeline.id,
      environmentId: environment.id,
      branch: `evidence-${suffix}`,
      gitSha: `evidence-sha-${suffix}`,
      logs: [
        { stream: "stdout", line: `archived-log-start-${suffix}` },
        { stream: "stdout", line: `Uploaded artifact: ${artifactName}` },
        { stream: "stderr", line: `archived-log-stderr-${suffix}` },
      ],
      artifactName,
      artifactHtml: `<html><body><h1>Artifact preview ${suffix}</h1></body></html>`,
    });

    await loginViaUi(page);
    await page.goto(`/runs/${run.id}`);
    await expect(page.getByRole("tab", { name: /Logs/ })).toBeVisible();
    await page.getByRole("tab", { name: /Logs/ }).click();
    await expect(page.getByText("Archived", { exact: true })).toBeVisible();
    await expect(page.getByText(`archived-log-start-${suffix}`)).toBeVisible();
    await page.getByPlaceholder("Search logs...").fill(`stderr-${suffix}`);
    await expect(page.getByText(`archived-log-stderr-${suffix}`)).toBeVisible();

    await page.getByRole("tab", { name: /Artifacts/ }).click();
    await expect(page.getByText(artifactName)).toBeVisible();

    const previewResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/artifacts/${run.artifactId}/preview-url`) &&
        response.status() === 200,
    );
    await page.getByRole("button", { name: `Preview ${artifactName}` }).click();
    const previewResponse = await previewResponsePromise;
    const previewBody = await previewResponse.json();
    expect(previewBody.preview_url).toContain(`/reports/${run.id}/`);

    await expect(page.locator('iframe[title="Allure Report Preview"]')).toBeVisible();
    await expect(
      page.frameLocator('iframe[title="Allure Report Preview"]').getByText(`Artifact preview ${suffix}`),
    ).toBeVisible();
  });
});
