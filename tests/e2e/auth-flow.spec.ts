import { expect, test, type Page, type Route } from "@playwright/test";

const project = {
  id: "11111111-1111-1111-1111-111111111111",
  tenant_id: "22222222-2222-2222-2222-222222222222",
  name: "Demo Project",
  slug: "demo-project",
  description: "Project used by the E2E login flow.",
  git_url: "https://github.com/example/demo-project.git",
  default_branch: "main",
  root_path: ".",
  status: "active",
  created_at: "2026-05-17T00:00:00Z",
  updated_at: "2026-05-17T00:00:00Z",
};

const run = {
  id: "33333333-3333-3333-3333-333333333333",
  tenant_id: project.tenant_id,
  project_id: project.id,
  pipeline_id: "44444444-4444-4444-4444-444444444444",
  environment_id: null,
  status: "passed",
  trigger_type: "manual",
  priority: 0,
  triggered_by: "55555555-5555-5555-5555-555555555555",
  git_ref: "main",
  git_sha: "abcdef123456",
  attempt: 1,
  started_at: "2026-05-17T00:01:00Z",
  finished_at: "2026-05-17T00:02:00Z",
  duration_ms: 60_000,
  summary: { total: 1, passed: 1, failed: 0 },
  error_message: null,
  created_at: "2026-05-17T00:00:30Z",
  updated_at: "2026-05-17T00:02:00Z",
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockApi(page: Page) {
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

    if (method === "GET" && path === `/api/v1/projects/${project.id}/pipelines`) {
      await fulfillJson(route, []);
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
      await fulfillJson(route, { data: [run], page: 1, per_page: 20, total: 1 });
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

  await page.getByRole("link", { name: /Demo Project/ }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}$`));
  await expect(page.getByRole("heading", { name: "Demo Project" })).toBeVisible();

  await page.getByRole("tab", { name: /Runs/ }).click();
  await expect(page.getByText("No runs found for this project.")).toBeVisible();

  await page.getByRole("button", { name: /Log out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in to QA Platform" })).toBeVisible();
});
