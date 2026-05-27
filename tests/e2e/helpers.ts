import { execFileSync } from "node:child_process";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export type Project = {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  description: string | null;
  git_url: string;
  default_branch: string;
  settings: Record<string, unknown>;
  silent_windows: Array<{ start_at: string; end_at: string; reason: string }>;
  updated_at: string;
};

export type Pipeline = {
  id: string;
  name: string;
};

export type Environment = {
  id: string;
  name: string;
  env_vars: Record<string, string>;
};

export type Paginated<T> = {
  data: T[];
  total: number;
};

type ApiUser = {
  id: string;
  username: string;
  email: string;
  role: string;
  tenant_id: string;
};

export type ApiLogin = {
  token: string;
  user: ApiUser;
};

export function uniqueSuffix() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function clearAuthRateLimits() {
  execFileSync(".venv/bin/python", ["-c", `
import asyncio
import redis.asyncio as redis

from qaplatform.config import Settings

async def main():
    client = redis.from_url(Settings().redis_url, decode_responses=True)
    keys = []
    async for key in client.scan_iter("rate_limit:*:/api/v1/auth/*"):
        keys.append(key)
    if keys:
        await client.delete(*keys)
    await client.aclose()

asyncio.run(main())
`], {
    cwd: process.cwd(),
    stdio: "ignore",
  });
}

export async function loginViaUi(page: Page) {
  clearAuthRateLimits();
  const adminPassword = process.env.E2E_ADMIN_PASSWORD || "admin123";
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(adminPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

export async function loginViaApi(
  request: APIRequestContext,
  overrides: { username?: string; password?: string; tenantId?: string } = {},
): Promise<ApiLogin> {
  clearAuthRateLimits();
  const response = await request.post("/api/v1/auth/login", {
    data: {
      username: overrides.username ?? "admin",
      password: overrides.password ?? process.env.E2E_ADMIN_PASSWORD ?? "admin123",
      ...(overrides.tenantId ? { tenant_id: overrides.tenantId } : {}),
    },
  });
  if (!response.ok()) {
    throw new Error(`API login failed: ${response.status()} ${await response.text()}`);
  }
  const body = await response.json();
  return { token: body.access_token, user: body.user };
}

export async function apiToken(request: APIRequestContext): Promise<string> {
  return (await loginViaApi(request)).token;
}

export function authHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
  };
}

export async function createProject(
  request: APIRequestContext,
  token: string,
  overrides: Partial<Project> & { name: string; slug: string },
): Promise<Project> {
  const response = await request.post("/api/v1/projects", {
    headers: authHeaders(token),
    data: {
      name: overrides.name,
      slug: overrides.slug,
      description: overrides.description ?? "Created by Playwright regression tests.",
      git_url: overrides.git_url ?? `https://github.com/example/${overrides.slug}.git`,
      git_auth_method: "none",
      default_branch: overrides.default_branch ?? "main",
      root_path: ".",
      shallow_clone: true,
      settings: overrides.settings ?? {},
    },
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

export async function updateProject(
  request: APIRequestContext,
  token: string,
  projectId: string,
  data: Record<string, unknown>,
): Promise<Project> {
  const response = await request.put(`/api/v1/projects/${projectId}`, {
    headers: authHeaders(token),
    data,
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

export async function ensureEnvironment(
  request: APIRequestContext,
  token: string,
  projectId: string,
  overrides: {
    name?: string;
    env_vars?: Record<string, string>;
  } = {},
): Promise<Environment> {
  const name = overrides.name ?? "E2E Environment";
  const createResponse = await request.post(`/api/v1/projects/${projectId}/environments`, {
    headers: authHeaders(token),
    data: {
      name,
      base_image: "python:3.12-alpine",
      network_policy: "allow",
      env_vars: overrides.env_vars ?? {},
    },
  });
  expect(createResponse.ok()).toBeTruthy();
  return createResponse.json();
}

export async function ensurePipeline(
  request: APIRequestContext,
  token: string,
  projectId: string,
  overrides: { name?: string; command?: string } = {},
): Promise<Pipeline> {
  const createResponse = await request.post(`/api/v1/projects/${projectId}/pipelines`, {
    headers: authHeaders(token),
    data: {
      name: overrides.name ?? "E2E Pipeline",
      stages: [
        {
          name: "Smoke",
          plugin: "pytest",
          phase: "execute",
          config: { command: overrides.command ?? "pytest" },
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

function runPythonJson<T>(script: string, payload: unknown): T {
  const output = execFileSync(".venv/bin/python", ["-c", script], {
    cwd: process.cwd(),
    encoding: "utf8",
    env: {
      ...process.env,
      E2E_PAYLOAD: JSON.stringify(payload),
    },
  });
  return JSON.parse(output);
}

export function createTenantUserViaDb(payload: {
  tenantId: string;
  username: string;
  email: string;
  password: string;
  role: "owner" | "admin" | "member" | "viewer";
}) {
  return runPythonJson<{ id: string }>(
    `
import asyncio
import json
import os
from argon2 import PasswordHasher
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from qaplatform.config import Settings
from qaplatform.infra.database.models import AppUser

async def main():
    data = json.loads(os.environ["E2E_PAYLOAD"])
    engine = create_async_engine(Settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        user = AppUser(
            tenant_id=data["tenantId"],
            username=data["username"],
            email=data["email"],
            password_hash=PasswordHasher().hash(data["password"]),
            role=data["role"],
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(json.dumps({"id": str(user.id)}))
    await engine.dispose()

asyncio.run(main())
`,
    payload,
  );
}

export function createRunWithResultsViaDb(payload: {
  tenantId: string;
  userId: string;
  projectId: string;
  pipelineId: string;
  environmentId: string;
  branch: string;
  gitSha: string;
  results: Array<{
    suite: string;
    name: string;
    status: "passed" | "failed" | "error" | "skipped";
    duration_ms?: number;
    error_message?: string | null;
    stack_trace?: string | null;
    tags?: string[];
    metadata?: Record<string, unknown>;
  }>;
}) {
  return runPythonJson<{ id: string }>(
    `
import asyncio
import json
import os
from uuid import UUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from qaplatform.config import Settings
from qaplatform.infra.database.models import Run, RunStatusEnum, TestResult, TestResultStatusEnum

async def main():
    data = json.loads(os.environ["E2E_PAYLOAD"])
    summary = {
        "total": len(data["results"]),
        "passed": sum(1 for item in data["results"] if item["status"] == "passed"),
        "failed": sum(1 for item in data["results"] if item["status"] in {"failed", "error"}),
        "skipped": sum(1 for item in data["results"] if item["status"] == "skipped"),
    }
    engine = create_async_engine(Settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        run = Run(
            tenant_id=UUID(data["tenantId"]),
            project_id=UUID(data["projectId"]),
            pipeline_id=UUID(data["pipelineId"]),
            environment_id=UUID(data["environmentId"]),
            status=RunStatusEnum.DONE,
            trigger_type="manual",
            priority=1,
            triggered_by=UUID(data["userId"]),
            git_ref=data["branch"],
            git_sha=data["gitSha"],
            summary=summary,
            duration_ms=1000,
            metadata_={"source": "playwright-e2e"},
        )
        session.add(run)
        await session.flush()
        run.retry_group_id = run.id
        for item in data["results"]:
            session.add(TestResult(
                run_id=run.id,
                suite=item["suite"],
                name=item["name"],
                status=TestResultStatusEnum(item["status"]),
                duration_ms=item.get("duration_ms", 1),
                error_message=item.get("error_message"),
                stack_trace=item.get("stack_trace"),
                tags=item.get("tags", []),
                metadata_=item.get("metadata", {}),
            ))
        await session.commit()
        print(json.dumps({"id": str(run.id)}))
    await engine.dispose()

asyncio.run(main())
`,
    payload,
  );
}

export function createActiveWebhookRunViaDb(payload: {
  tenantId: string;
  userId: string;
  projectId: string;
  pipelineId: string;
  environmentId: string;
  branch: string;
  gitSha: string;
  dedupKey: string;
}) {
  return runPythonJson<{ id: string }>(
    `
import asyncio
import json
import os
from uuid import UUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from qaplatform.config import Settings
from qaplatform.infra.database.models import Run, RunStatusEnum

async def main():
    data = json.loads(os.environ["E2E_PAYLOAD"])
    engine = create_async_engine(Settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        run = Run(
            tenant_id=UUID(data["tenantId"]),
            project_id=UUID(data["projectId"]),
            pipeline_id=UUID(data["pipelineId"]),
            environment_id=UUID(data["environmentId"]),
            status=RunStatusEnum.QUEUED,
            trigger_type="webhook",
            priority=1,
            triggered_by=UUID(data["userId"]),
            git_ref=f"refs/heads/{data['branch']}",
            git_sha=data["gitSha"],
            dedup_key=data["dedupKey"],
            metadata_={"source": "playwright-e2e"},
        )
        session.add(run)
        await session.flush()
        run.retry_group_id = run.id
        await session.commit()
        print(json.dumps({"id": str(run.id)}))
    await engine.dispose()

asyncio.run(main())
`,
    payload,
  );
}
