import { expect, test } from "@playwright/test";
import {
  authHeaders,
  createActiveWebhookRunViaDb,
  createProject,
  createRunWithResultsViaDb,
  createTenantUserViaDb,
  ensureEnvironment,
  ensurePipeline,
  loginViaApi,
  loginViaUi,
  uniqueSuffix,
  updateProject,
  type Paginated,
} from "./helpers";

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
    expect(response.ok()).toBeTruthy();
    const refreshed = await response.json();
    expect(refreshed.silent_windows).toHaveLength(1);
    expect(refreshed.silent_windows[0].reason).toBe(`Release freeze ${suffix}`);
    expect(refreshed.silent_windows[0].start_at).toMatch(/(Z|[+-]\d\d:\d\d)$/);
    expect(refreshed.silent_windows[0].end_at).toMatch(/(Z|[+-]\d\d:\d\d)$/);
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

    await loginViaUi(page);
    await page.goto(`/projects/${project.id}`);
    await expect(page.getByRole("heading", { level: 1, name: project.name })).toBeVisible();
    await page.getByRole("tab", { name: /Environments/ }).click();

    await expect(page.getByText(`Masked Env ${suffix}`)).toBeVisible();
    await expect(page.locator('input[placeholder="KEY"]').first()).toHaveValue("API_TOKEN");
    await expect(page.getByText(secret)).toHaveCount(0);

    const valueInput = page.locator('input[placeholder="VALUE"]').first();
    await expect(valueInput).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: "Show value" }).click();
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
    expect(createRule.ok()).toBeTruthy();

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
    expect(await filtered.json()).toMatchObject({
      status: "filtered",
      reason: "branch_not_allowed",
    });

    const dedupKey = `playwright-e2e:${project.git_url}:${gitSha}:${allowedBranch}`;
    createActiveWebhookRunViaDb({
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
    expect(runsResponse.ok()).toBeTruthy();
    const runs = (await runsResponse.json()) as Paginated<{ git_sha: string | null; git_ref: string }>;
    expect(runs.data.filter((run) => run.git_sha === gitSha)).toHaveLength(1);
    expect(runs.data.some((run) => run.git_ref === `refs/heads/${filteredBranch}`)).toBe(false);

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

    const ownerAudit = await request.get("/api/v1/audit-events?per_page=50", {
      headers: authHeaders(ownerLogin.token),
    });
    expect(ownerAudit.status()).toBe(200);
    const ownerAuditBody = await ownerAudit.json();
    expect(
      ownerAuditBody.data.some(
        (event: { action: string; resource_id: string }) =>
          event.action === "project.create" && event.resource_id === project.id,
      ),
    ).toBe(true);

    const memberPassword = `member-pass-${suffix}`;
    const member = createTenantUserViaDb({
      tenantId: ownerLogin.user.tenant_id,
      username: `member_${suffix.replace(/-/g, "_")}`,
      email: `member-${suffix}@e2e.local`,
      password: memberPassword,
      role: "member",
    });
    expect(member.id).toBeTruthy();

    const memberLogin = await loginViaApi(request, {
      username: `member_${suffix.replace(/-/g, "_")}`,
      password: memberPassword,
      tenantId: ownerLogin.user.tenant_id,
    });
    const memberAudit = await request.get("/api/v1/audit-events", {
      headers: authHeaders(memberLogin.token),
    });
    expect(memberAudit.status()).toBe(403);
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
    const failedBody = await failedResponse.json();
    expect(failedBody.total).toBe(1);
    expect(failedBody.data[0].name).toBe(`test_checkout_timeout_${suffix}`);

    const suiteResponse = await request.get(`/api/v1/runs/${run.id}/results?suite=billing`, {
      headers: authHeaders(ownerLogin.token),
    });
    expect(suiteResponse.status()).toBe(200);
    const suiteBody = await suiteResponse.json();
    expect(suiteBody.total).toBe(1);
    expect(suiteBody.data[0].name).toBe(`test_billing_skipped_${suffix}`);

    const queryResponse = await request.get(`/api/v1/runs/${run.id}/results?q=timeout-${suffix}`, {
      headers: authHeaders(ownerLogin.token),
    });
    expect(queryResponse.status()).toBe(200);
    const queryBody = await queryResponse.json();
    expect(queryBody.total).toBe(1);
    expect(queryBody.data[0].status).toBe("failed");

    await loginViaUi(page);
    await page.goto(`/runs/${run.id}`);
    await expect(page.getByText(`test_checkout_ok_${suffix}`)).toBeVisible();
    await expect(page.getByText(`test_checkout_timeout_${suffix}`)).toBeVisible();
    await expect(page.getByText(`test_billing_skipped_${suffix}`)).toBeVisible();
  });
});
