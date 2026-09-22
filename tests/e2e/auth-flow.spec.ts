import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

const project = {
  id: "11111111-1111-1111-1111-111111111111",
  tenant_id: "22222222-2222-2222-2222-222222222222",
  name: "Demo Project",
  slug: "demo-project",
  description: "Project used by the E2E login flow.",
  git_url: "https://github.com/example/demo-project.git",
  git_auth_method: "none",
  credential_id: null,
  default_branch: "main",
  root_path: ".",
  shallow_clone: true,
  default_env_id: "66666666-6666-6666-6666-666666666666",
  settings: {},
  silent_windows: [],
  status: "active",
  created_by: "55555555-5555-5555-5555-555555555555",
  created_at: "2026-05-17T00:00:00Z",
  updated_at: "2026-05-17T00:00:00Z",
};

const run = {
  id: "33333333-3333-3333-3333-333333333333",
  tenant_id: project.tenant_id,
  project_id: project.id,
  pipeline_id: "44444444-4444-4444-4444-444444444444",
  pipeline_name: "CI Smoke",
  environment_id: project.default_env_id,
  status: "done",
  trigger_type: "manual",
  priority: 1,
  triggered_by: "55555555-5555-5555-5555-555555555555",
  git_ref: "main",
  git_sha: "abcdef123456abcdef123456abcdef123456abcd",
  attempt: 1,
  started_at: "2026-05-17T00:01:00Z",
  finished_at: "2026-05-17T00:02:00Z",
  duration_ms: 60_000,
  summary: { total: 3, passed: 2, failed: 1, error: 0 },
  error_message: null,
  created_at: "2026-05-17T00:00:30Z",
  updated_at: "2026-05-17T00:02:00Z",
};

const zeroResultRun = {
  ...run,
  id: "77777777-7777-7777-7777-777777777777",
  pipeline_id: "88888888-8888-8888-8888-888888888888",
  pipeline_name: "CI Empty Collector",
  git_ref: "empty-results",
  git_sha: "123456abcdef123456abcdef123456abcdef123456",
  summary: { total: 0, passed: 0, failed: 0, skipped: 0, error: 0 },
};

const legacySummaryRun = {
  ...run,
  id: "99999999-9999-9999-9999-999999999999",
  pipeline_id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
  pipeline_name: "CI Legacy Summary",
  git_ref: "legacy-summary",
  git_sha: "fedcba123456fedcba123456fedcba123456fedc",
  summary: { passed: 1, failed: 0, skipped: 0, error: 0 },
};

const releaseAutomationToken = {
  token_id: "tok_release_automation",
  name: "Release automation",
  scopes: ["runs:read", "artifacts:read"],
  expires_at: "2026-08-17T00:00:00Z",
  last_used_at: null,
  is_revoked: false,
  created_at: "2026-05-17T00:00:00Z",
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function expectTableCells(row: Locator, expectedCells: Array<[number, string | RegExp]>) {
  const cells = row.locator("td");
  for (const [index, expectedText] of expectedCells) {
    await expect(cells.nth(index)).toHaveText(expectedText);
  }
}

async function mockApi(page: Page) {
  let apiTokens = [releaseAutomationToken];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "POST" && path === "/api/v1/auth/refresh") {
      await fulfillJson(route, { detail: "Missing refresh token" }, 401);
      return;
    }

    if (method === "POST" && path === "/api/v1/auth/login") {
      await fulfillJson(route, {
        access_token: "e2e-access-token",
        token_type: "bearer",
        user: {
          id: run.triggered_by,
          username: "admin",
          email: "admin@example.com",
          role: "admin",
          tenant_id: project.tenant_id,
        },
      });
      return;
    }

    if (method === "POST" && path === "/api/v1/auth/logout") {
      await route.fulfill({ status: 204 });
      return;
    }

    if (method === "GET" && path === "/api/v1/auth/tokens") {
      await fulfillJson(route, {
        data: apiTokens,
        page: 1,
        per_page: 20,
        total: apiTokens.length,
      });
      return;
    }

    if (method === "POST" && path === "/api/v1/auth/tokens") {
      const payload = request.postDataJSON() as {
        name: string;
        scopes?: string[];
        expires_days?: number;
      };
      const created = {
        token_id: "tok_nightly",
        name: payload.name,
        scopes: payload.scopes ?? ["*"],
        expires_at: "2026-06-16T00:00:00Z",
        last_used_at: null,
        is_revoked: false,
        created_at: "2026-05-17T00:03:00Z",
      };
      apiTokens = [created, ...apiTokens];
      await fulfillJson(route, {
        ...created,
        token: "qap_generated_nightly_token",
      }, 201);
      return;
    }

    if (method === "DELETE" && path.startsWith("/api/v1/auth/tokens/")) {
      const tokenId = path.split("/").at(-1);
      apiTokens = apiTokens.map((token) =>
        token.token_id === tokenId ? { ...token, is_revoked: true } : token,
      );
      await route.fulfill({ status: 204 });
      return;
    }

    if (method === "GET" && path === `/api/v1/projects/${project.id}/pipelines`) {
      await fulfillJson(route, { data: [], page: 1, per_page: 20, total: 0 });
      return;
    }

    if (method === "GET" && path === `/api/v1/projects/${project.id}`) {
      await fulfillJson(route, project);
      return;
    }

    if (method === "GET" && path === "/api/v1/projects") {
      await fulfillJson(route, { data: [project], page: 1, per_page: 20, total: 1 });
      return;
    }

    if (method === "GET" && path === "/api/v1/runs") {
      // The project detail Runs tab scopes the query with ?project_id=...;
      // this fixture's project has no runs, so it must render the empty state.
      // The global runs list (no project_id) returns the three seeded runs.
      if (url.searchParams.has("project_id")) {
        await fulfillJson(route, { data: [], page: 1, per_page: 5, total: 0 });
        return;
      }
      await fulfillJson(route, {
        data: [run, zeroResultRun, legacySummaryRun],
        page: 1,
        per_page: 20,
        total: 3,
      });
      return;
    }

    await fulfillJson(route, { detail: `Unhandled E2E route: ${method} ${path}` }, 404);
  });
}

test("login, open a project, view runs, then logout back to login", async ({ page }) => {
  await mockApi(page);

  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  await page.getByRole("link", { name: /^Runs$/ }).click();
  await expect(page).toHaveURL(/\/runs$/);
  await expect(page.getByRole("heading", { name: "Recent Runs" })).toBeVisible();
  const runRow = page.getByRole("row", { name: /CI Smoke/ });
  await expectTableCells(runRow, [
    [0, "Failed"],
    [1, "Medium"],
    [2, "CI Smoke"],
    [3, "main"],
    [4, new RegExp(`${run.triggered_by}\\s*Manual`)],
    [5, "1m 0s"],
  ]);
  const emptyCollectorRow = page.getByRole("row", { name: /CI Empty Collector/ });
  await expectTableCells(emptyCollectorRow, [
    [0, "Unknown"],
    [1, "Medium"],
    [2, "CI Empty Collector"],
    [3, "empty-results"],
    [4, new RegExp(`${run.triggered_by}\\s*Manual`)],
    [5, "1m 0s"],
  ]);
  const legacySummaryRow = page.getByRole("row", { name: /CI Legacy Summary/ });
  await expectTableCells(legacySummaryRow, [
    [0, "Passed"],
    [1, "Medium"],
    [2, "CI Legacy Summary"],
    [3, "legacy-summary"],
    [4, new RegExp(`${run.triggered_by}\\s*Manual`)],
    [5, "1m 0s"],
  ]);

  await page.getByRole("link", { name: /^Projects$/ }).click();
  await page.getByRole("link", { name: /Demo Project/ }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}$`));
  await expect(page.getByRole("heading", { name: "Demo Project" })).toBeVisible();

  await page.getByRole("tab", { name: /Runs/ }).click();
  await expect(page.getByText("No runs found for this project.")).toBeVisible();

  await page.getByRole("link", { name: /^Settings$/ }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  const releaseTokenRow = page.getByRole("row", { name: /Release automation/ });
  await expectTableCells(releaseTokenRow, [
    [0, "Release automation"],
    [1, "runs:read, artifacts:read"],
    [3, "-"],
    [5, "Active"],
  ]);

  await page.getByRole("button", { name: "Create token" }).click();
  const createDialog = page.getByRole("dialog", { name: "Create token" });
  await createDialog.getByLabel("Name").fill("Nightly token");
  await createDialog.getByLabel("Scopes").fill("runs:read, artifacts:read");
  await createDialog.getByLabel("Expires in days").fill("30");
  await createDialog.getByRole("button", { name: "Create token" }).click();

  await expect(page.getByLabel("Created token value")).toHaveValue("qap_generated_nightly_token");
  const nightlyTokenRow = page.getByRole("row", { name: /Nightly token/ });
  await expectTableCells(nightlyTokenRow, [
    [0, "Nightly token"],
    [1, "runs:read, artifacts:read"],
    [3, "-"],
    [5, "Active"],
  ]);
  await nightlyTokenRow.getByRole("button", { name: "Revoke Nightly token" }).click();
  await page.getByRole("button", { name: "Revoke" }).click();
  await expect(nightlyTokenRow.locator("td").nth(5)).toHaveText("Revoked");
  await expect(nightlyTokenRow.getByRole("button", { name: "Revoke Nightly token" })).toBeDisabled();

  await page.getByRole("button", { name: /Log out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in to QA Platform" })).toBeVisible();
});
