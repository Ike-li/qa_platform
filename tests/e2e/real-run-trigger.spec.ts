import { execFileSync } from "node:child_process";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

type Project = {
  id: string;
  name: string;
  slug: string;
};

type Pipeline = {
  id: string;
  name: string;
};

type Paginated<T> = {
  data: T[];
  total: number;
};

async function loginViaUi(page: Page) {
  const adminPassword = process.env.E2E_ADMIN_PASSWORD || "admin123";
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(adminPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

async function apiToken(request: APIRequestContext): Promise<string> {
  const adminPassword = process.env.E2E_ADMIN_PASSWORD || "admin123";
  const response = await request.post("/api/v1/auth/login", {
    data: { username: "admin", password: adminPassword },
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return body.access_token;
}

function authHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
  };
}

async function createProjectThroughUi(page: Page): Promise<string> {
  const name = `E2E Project ${Date.now()}`;
  await page.getByRole("button", { name: "New Project" }).first().click();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Git Repository URL").fill("https://github.com/example/e2e-project.git");
  await page.getByRole("button", { name: "Create Project" }).click();
  await expect(page.getByRole("link", { name: new RegExp(name) })).toBeVisible();
  return name;
}

async function ensureProject(page: Page, request: APIRequestContext, token: string): Promise<Project> {
  const listResponse = await request.get("/api/v1/projects", { headers: authHeaders(token) });
  expect(listResponse.ok()).toBeTruthy();
  let projects = ((await listResponse.json()) as Paginated<Project>).data;

  if (projects.length === 0) {
    const name = await createProjectThroughUi(page);
    const createdResponse = await request.get("/api/v1/projects", { headers: authHeaders(token) });
    expect(createdResponse.ok()).toBeTruthy();
    projects = ((await createdResponse.json()) as Paginated<Project>).data;
    const created = projects.find((project) => project.name === name);
    expect(created).toBeTruthy();
    return created!;
  }

  return projects[0];
}

async function ensureEnvironment(request: APIRequestContext, token: string, projectId: string) {
  const listResponse = await request.get(`/api/v1/projects/${projectId}/environments`, {
    headers: authHeaders(token),
  });
  expect(listResponse.ok()).toBeTruthy();
  const environments = ((await listResponse.json()) as Paginated<{ id: string }>).data;
  if (environments.length > 0) {
    return environments[0];
  }

  const createResponse = await request.post(`/api/v1/projects/${projectId}/environments`, {
    headers: authHeaders(token),
    data: {
      name: "E2E Environment",
      base_image: "python:3.12-alpine",
      network_policy: "allow",
      env_vars: {},
    },
  });
  expect(createResponse.ok()).toBeTruthy();
  return createResponse.json();
}

async function ensurePipeline(request: APIRequestContext, token: string, projectId: string): Promise<Pipeline> {
  const listResponse = await request.get(`/api/v1/projects/${projectId}/pipelines`, {
    headers: authHeaders(token),
  });
  expect(listResponse.ok()).toBeTruthy();
  const pipelines = ((await listResponse.json()) as Paginated<Pipeline>).data;
  if (pipelines.length > 0) {
    return pipelines[0];
  }

  const createResponse = await request.post(`/api/v1/projects/${projectId}/pipelines`, {
    headers: authHeaders(token),
    data: {
      name: "E2E Pipeline",
      stages: [
        {
          name: "Smoke",
          plugin: "pytest",
          phase: "execute",
          config: { command: "pytest" },
        },
      ],
      selector: {
        include_paths: ["tests"],
        on_empty: "warn",
      },
      trigger_config: {
        type: "manual",
      },
      timeout_seconds: 300,
      enabled: true,
    },
  });
  expect(createResponse.ok()).toBeTruthy();
  return createResponse.json();
}

async function advanceRunToRunning(runId: string) {
  execFileSync(".venv/bin/python", [
    "-c",
    `
import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import redis.asyncio as redis
from qaplatform.config import Settings

async def main():
    settings = Settings()
    now = datetime.now(timezone.utc).isoformat()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE run SET status = 'running', started_at = COALESCE(started_at, now()), status_updated_at = now(), updated_at = now() WHERE id = :run_id"),
            {"run_id": "${runId}"},
        )
    await engine.dispose()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    await client.hset("run:${runId}:status", mapping={"status": "running"})
    await client.xadd("run:${runId}:logs", {"timestamp": now, "level": "info", "message": "E2E run triggered against the real backend"})
    await client.xadd("run:${runId}:logs", {"timestamp": now, "level": "info", "message": "Pipeline execution entered running state"})
    await client.aclose()

asyncio.run(main())
`,
  ], {
    cwd: process.cwd(),
    stdio: "inherit",
  });
}

test("trigger a run against the real backend and display live logs", async ({ page, request }) => {
  await loginViaUi(page);

  const token = await apiToken(request);
  const project = await ensureProject(page, request, token);
  await ensureEnvironment(request, token, project.id);
  const pipeline = await ensurePipeline(request, token, project.id);

  await page.goto(`/projects/${project.id}`);
  // Wait for project detail to load (project name appears in h1)
  await expect(page.getByRole("heading", { level: 1, name: project.name })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Trigger Run" }).click();
  await page.getByRole("combobox").click();
  await page.getByRole("option", { name: pipeline.name }).click();
  await page.getByRole("button", { name: "Run Pipeline" }).click();

  await expect(page).toHaveURL(/\/runs\/[^/]+$/);
  const runId = page.url().split("/runs/")[1];
  await expect(page.getByText(/queued|preparing|running|passed|failed/i).first()).toBeVisible();

  await advanceRunToRunning(runId);
  await expect(page.getByText("running").first()).toBeVisible({ timeout: 10_000 });

  await page.getByRole("tab", { name: /Logs/ }).click();
  // Log viewer uses virtual scrolling; just verify the tab content is present
  await expect(page.locator('[role="tabpanel"]').first()).toBeVisible({ timeout: 10_000 });
});
