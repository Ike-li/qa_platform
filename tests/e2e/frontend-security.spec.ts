import { expect, test } from "@playwright/test";
import {
  createProject,
  createRunWithArchivedEvidenceViaDb,
  ensureEnvironment,
  ensurePipeline,
  loginViaApi,
  loginViaUi,
  uniqueSuffix,
} from "./helpers";

test.describe("frontend security invariants", () => {
  test("artifact preview iframe has sandbox without allow-same-origin", async ({
    page,
    request,
  }) => {
    const suffix = uniqueSuffix();
    const { token, user } = await loginViaApi(request);
    const project = await createProject(request, token, {
      name: `E2E Sec ${suffix}`,
      slug: `e2e-sec-${suffix}`,
    });
    const environment = await ensureEnvironment(request, token, project.id);
    const pipeline = await ensurePipeline(request, token, project.id);

    const artifactName = `allure-report/index-${suffix}.html`;
    const run = createRunWithArchivedEvidenceViaDb({
      tenantId: user.tenant_id,
      userId: user.id,
      projectId: project.id,
      pipelineId: pipeline.id,
      environmentId: environment.id,
      branch: `sec-${suffix}`,
      gitSha: `sec-sha-${suffix}`,
      logs: [{ stream: "stdout", line: `Test artifact security ${suffix}` }],
      artifactName,
      artifactHtml: `<html><body><h1>Security test ${suffix}</h1></body></html>`,
    });

    await loginViaUi(page);
    await page.goto(`/runs/${run.id}`);
    await page.waitForLoadState("networkidle");

    // Open artifact preview
    await page.getByRole("button", { name: /preview/i }).first().click();
    await page.waitForSelector("iframe", { timeout: 5000 });

    // Verify iframe sandbox attribute
    const iframe = page.locator("iframe").first();
    const sandbox = await iframe.getAttribute("sandbox");
    const referrerPolicy = await iframe.getAttribute("referrerPolicy");

    expect(sandbox).toBeTruthy();
    expect(sandbox).toContain("allow-scripts");
    expect(sandbox).not.toContain("allow-same-origin");
    expect(referrerPolicy).toBe("no-referrer");
  });

  test("artifact preview rejects javascript: protocol URLs", async ({
    page,
    request,
  }) => {
    const suffix = uniqueSuffix();
    const { token, user } = await loginViaApi(request);
    const project = await createProject(request, token, {
      name: `E2E JSUrl ${suffix}`,
      slug: `e2e-jsurl-${suffix}`,
    });
    const environment = await ensureEnvironment(request, token, project.id);
    const pipeline = await ensurePipeline(request, token, project.id);

    const artifactName = `report-${suffix}.html`;
    const run = createRunWithArchivedEvidenceViaDb({
      tenantId: user.tenant_id,
      userId: user.id,
      projectId: project.id,
      pipelineId: pipeline.id,
      environmentId: environment.id,
      branch: `jsurl-${suffix}`,
      gitSha: `jsurl-sha-${suffix}`,
      logs: [{ stream: "stdout", line: `Test JS URL ${suffix}` }],
      artifactName,
      artifactHtml: `<html><body><h1>Test ${suffix}</h1></body></html>`,
    });

    await loginViaUi(page);
    await page.goto(`/runs/${run.id}`);
    await page.waitForLoadState("networkidle");

    // Mock artifact preview URL API to return javascript: URL
    await page.route("**/api/v1/artifacts/*/preview-url", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ url: "javascript:alert('XSS')" }),
      });
    });

    // Try to preview artifact
    await page.getByRole("button", { name: /preview/i }).first().click();

    // Wait a bit to ensure no iframe is created
    await page.waitForTimeout(1000);

    // Verify no iframe appeared (preview was blocked)
    const iframes = page.locator("iframe");
    await expect(iframes).toHaveCount(0);

    // Verify error toast appeared
    await expect(page.getByText(/failed/i)).toBeVisible({ timeout: 2000 });
  });

  test("artifact download rejects file: protocol URLs", async ({
    page,
    request,
  }) => {
    const suffix = uniqueSuffix();
    const { token, user } = await loginViaApi(request);
    const project = await createProject(request, token, {
      name: `E2E FileUrl ${suffix}`,
      slug: `e2e-fileurl-${suffix}`,
    });
    const environment = await ensureEnvironment(request, token, project.id);
    const pipeline = await ensurePipeline(request, token, project.id);

    const artifactName = `report-${suffix}.html`;
    const run = createRunWithArchivedEvidenceViaDb({
      tenantId: user.tenant_id,
      userId: user.id,
      projectId: project.id,
      pipelineId: pipeline.id,
      environmentId: environment.id,
      branch: `fileurl-${suffix}`,
      gitSha: `fileurl-sha-${suffix}`,
      logs: [{ stream: "stdout", line: `Test file URL ${suffix}` }],
      artifactName,
      artifactHtml: `<html><body><h1>Test ${suffix}</h1></body></html>`,
    });

    await loginViaUi(page);
    await page.goto(`/runs/${run.id}`);
    await page.waitForLoadState("networkidle");

    // Mock artifact download URL API to return file: URL
    await page.route("**/api/v1/artifacts/*/download-url", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ url: "file:///etc/passwd" }),
      });
    });

    // Listen for window.open calls (should not happen)
    let windowOpened = false;
    page.on("popup", () => {
      windowOpened = true;
    });

    // Try to download artifact
    await page.getByRole("button", { name: /download/i }).first().click();

    // Wait to ensure no window.open happened
    await page.waitForTimeout(1000);

    expect(windowOpened).toBe(false);

    // Verify error toast appeared
    await expect(page.getByText(/failed/i)).toBeVisible({ timeout: 2000 });
  });
});
