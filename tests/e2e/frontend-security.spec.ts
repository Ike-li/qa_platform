import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import {
  createProject,
  createRunWithArchivedEvidenceViaDb,
  ensureEnvironment,
  ensurePipeline,
  loginViaApi,
  loginViaUi,
  uniqueSuffix,
} from "./helpers";

async function setupTestRun(request: APIRequestContext, testName: string) {
  const suffix = uniqueSuffix();
  const { token, user } = await loginViaApi(request);
  const project = await createProject(request, token, {
    name: `E2E ${testName} ${suffix}`,
    slug: `e2e-${testName.toLowerCase()}-${suffix}`,
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
    branch: `${testName.toLowerCase()}-${suffix}`,
    gitSha: `${testName.toLowerCase()}-sha-${suffix}`,
    logs: [{ stream: "stdout", line: `Test ${testName} ${suffix}` }],
    artifactName,
    artifactHtml: `<html><body><h1>Test ${suffix}</h1></body></html>`,
  });

  return { run, suffix };
}

async function navigateToRun(page: Page, runId: string) {
  await loginViaUi(page);
  await page.goto(`/runs/${runId}`);
  await page.waitForLoadState("networkidle");
}

test.describe("frontend security invariants", () => {
  test("artifact preview iframe has sandbox without allow-same-origin", async ({
    page,
    request,
  }) => {
    const { run } = await setupTestRun(request, "Sec");
    await navigateToRun(page, run.id);

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
    const { run } = await setupTestRun(request, "JSUrl");

    await loginViaUi(page);

    // Mock artifact preview URL API to return javascript: URL (set before navigation)
    await page.route("**/api/v1/artifacts/*/preview-url", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ url: "javascript:alert('XSS')" }),
      });
    });

    await page.goto(`/runs/${run.id}`);
    await page.waitForLoadState("networkidle");

    // Try to preview artifact
    await page.getByRole("button", { name: /preview/i }).first().click();

    // Verify no iframe appeared (preview was blocked)
    const iframes = page.locator("iframe");
    await expect(iframes).toHaveCount(0, { timeout: 2000 });

    // Verify error toast appeared with specific message
    await expect(page.getByText("Failed to load preview")).toBeVisible({ timeout: 2000 });
  });

  test("artifact download rejects file: protocol URLs", async ({
    page,
    request,
  }) => {
    const { run } = await setupTestRun(request, "FileUrl");

    await loginViaUi(page);

    // Mock artifact download URL API to return file: URL (set before navigation)
    await page.route("**/api/v1/artifacts/*/download-url", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ url: "file:///etc/passwd" }),
      });
    });

    await page.goto(`/runs/${run.id}`);
    await page.waitForLoadState("networkidle");

    // Listen for window.open calls (should not happen)
    let windowOpened = false;
    page.once("popup", () => {
      windowOpened = true;
    });

    // Try to download artifact
    await page.getByRole("button", { name: /download/i }).first().click();

    // Wait for error toast to confirm the download was blocked
    await expect(page.getByText("Failed to download artifact")).toBeVisible({ timeout: 2000 });

    // Verify no window.open happened
    expect(windowOpened).toBe(false);
  });
});
