import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import {
  authHeaders,
  createProject,
  ensureEnvironment,
  ensurePipeline,
  loginViaApi,
  loginViaUi,
  uniqueSuffix,
  type Paginated,
} from "./helpers";

type BackendRun = {
  id: string;
  status: string;
  summary: {
    total?: number;
    passed?: number;
    failed?: number;
    skipped?: number;
    error?: number;
    pass_rate?: number;
  } | null;
  error_message: string | null;
};

type ArchivedLog = {
  line: string;
  stream: string;
};

type Artifact = {
  name: string;
  type: string;
};

type TestResult = {
  name: string;
  status: string;
};

const EXTERNAL_STACK_GIT_URL =
  process.env.QAP_EXTERNAL_STACK_GIT_URL ?? "https://github.com/octocat/Hello-World.git";
const EXTERNAL_STACK_GIT_REF = process.env.QAP_EXTERNAL_STACK_GIT_REF ?? "master";
const TERMINAL_BACKEND_STATUSES = new Set(["done", "failed", "cancelled", "timeout"]);

test.skip(
  process.env.QAP_E2E_WORKER !== "1",
  "set QAP_E2E_WORKER=1 to run the worker-backed E2E",
);

test.describe.configure({ mode: "serial" });
test.setTimeout(360_000);

function workerSetupScript(testCaseName: string): string {
  // Runner simulator: this keeps the browser-to-platform E2E deterministic
  // while backend integration tests retain real pytest package coverage.
  const pytestSource = [
    "from pathlib import Path",
    "import sys",
    `test_case_name = ${JSON.stringify(testCaseName)}`,
    "junit = 'results/junit.xml'",
    "for arg in sys.argv[1:]:",
    "    if arg.startswith('--junitxml='):",
    "        junit = arg.split('=', 1)[1]",
    "path = Path(junit)",
    "path.parent.mkdir(parents=True, exist_ok=True)",
    "path.write_text(" +
      JSON.stringify(
        '<testsuite name="playwright-real-worker" tests="1" failures="0" errors="0" skipped="0">' +
          `<testcase classname="playwright_real_worker" name="${testCaseName}" time="0.01" />` +
          "</testsuite>",
      ) +
      ", encoding='utf-8')",
    "print('===== 1 passed in 0.01s =====', flush=True)",
  ].join("\n");

  return [
    "python - <<'PY'",
    "from pathlib import Path",
    "workspace = Path('/workspace')",
    "(workspace / 'tests').mkdir(exist_ok=True)",
    "(workspace / 'tests' / 'test_playwright_real_worker.py').write_text(" +
      JSON.stringify(
        "from pathlib import Path\n\n" +
          "def test_playwright_real_worker():\n" +
          "    assert Path('pytest.py').exists()\n",
      ) +
      ", encoding='utf-8')",
    `(workspace / 'pytest.py').write_text(${JSON.stringify(pytestSource)}, encoding='utf-8')`,
    "PY",
  ].join("\n");
}

function runIdFromPage(page: Page): string {
  const runId = new URL(page.url()).pathname.split("/").filter(Boolean).at(-1);
  if (!runId) {
    throw new Error(`Could not extract run id from ${page.url()}`);
  }
  return runId;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function expectPassedResultRow(page: Page, testCaseName: string, timeout = 5_000) {
  const row = page.getByRole("row", { name: new RegExp(escapeRegExp(testCaseName)) });
  await expect(row).toBeVisible({ timeout });
  const cells = row.locator("td");
  await expect(cells.nth(1)).toHaveText(testCaseName);
  await expect(cells.nth(3)).toHaveText("Passed");
}

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function assertOk(response: { ok(): boolean; status(): number; text(): Promise<string> }, context: string) {
  if (!response.ok()) {
    throw new Error(`${context} failed with ${response.status()}: ${await response.text()}`);
  }
}

async function waitForRunTerminal(
  request: APIRequestContext,
  token: string,
  runId: string,
  timeoutMs = 240_000,
): Promise<BackendRun> {
  const deadline = Date.now() + timeoutMs;
  let lastRun: BackendRun | null = null;

  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/runs/${runId}`, {
      headers: authHeaders(token),
    });
    await assertOk(response, `GET /runs/${runId}`);
    lastRun = (await response.json()) as BackendRun;
    if (TERMINAL_BACKEND_STATUSES.has(lastRun.status)) {
      return lastRun;
    }
    await sleep(3000);
  }

  throw new Error(`Run ${runId} did not reach a terminal status: ${JSON.stringify(lastRun)}`);
}

async function waitForRunResults(
  request: APIRequestContext,
  token: string,
  runId: string,
  timeoutMs = 60_000,
): Promise<TestResult[]> {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/runs/${runId}/results`, {
      headers: authHeaders(token),
    });
    await assertOk(response, `GET /runs/${runId}/results`);
    const body = (await response.json()) as Paginated<TestResult>;
    if (body.data.length > 0) {
      return body.data;
    }
    await sleep(2000);
  }

  throw new Error(`Run ${runId} did not expose collected test results`);
}

async function waitForArtifacts(
  request: APIRequestContext,
  token: string,
  runId: string,
  timeoutMs = 60_000,
): Promise<Artifact[]> {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/runs/${runId}/artifacts`, {
      headers: authHeaders(token),
    });
    await assertOk(response, `GET /runs/${runId}/artifacts`);
    const body = (await response.json()) as Paginated<Artifact>;
    if (body.data.some((artifact) => artifact.name === "junit.xml")) {
      return body.data;
    }
    await sleep(2000);
  }

  throw new Error(`Run ${runId} did not expose junit.xml artifact metadata`);
}

async function waitForArchivedLogsContaining(
  request: APIRequestContext,
  token: string,
  runId: string,
  expectedMessages: string[],
  timeoutMs = 90_000,
): Promise<string[]> {
  const deadline = Date.now() + timeoutMs;
  let lastLines: string[] = [];

  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/runs/${runId}/logs/archive?per_page=1000`, {
      headers: authHeaders(token),
    });
    if (response.status() === 404) {
      await sleep(2000);
      continue;
    }
    await assertOk(response, `GET /runs/${runId}/logs/archive`);
    const body = (await response.json()) as Paginated<ArchivedLog>;
    lastLines = body.data.map((entry) => entry.line);
    if (expectedMessages.every((message) => lastLines.some((line) => line.includes(message)))) {
      return lastLines;
    }
    await sleep(2000);
  }

  throw new Error(
    `Archived logs for ${runId} did not contain ${JSON.stringify(expectedMessages)}; last=${JSON.stringify(
      lastLines,
    )}`,
  );
}

test("trigger a run through the UI and verify the real worker evidence", async ({ page, request }) => {
  const suffix = uniqueSuffix();
  const testCaseName = `playwright_real_worker_${suffix.replace(/-/g, "_")}`;
  const login = await loginViaApi(request);
  const project = await createProject(request, login.token, {
    name: `E2E Worker ${suffix}`,
    slug: `e2e-worker-${suffix}`,
    git_url: EXTERNAL_STACK_GIT_URL,
    default_branch: EXTERNAL_STACK_GIT_REF,
  });
  const environment = await ensureEnvironment(request, login.token, project.id, {
    name: `Worker Env ${suffix}`,
    base_image: "python:3.12-alpine",
    network_policy: "allow",
    env_vars: {},
    setup_script: workerSetupScript(testCaseName),
    memory_mb: 512,
    cpu_cores: 1,
    max_artifact_size_mb: 10,
    max_artifacts_count: 5,
  });
  const pipeline = await ensurePipeline(request, login.token, project.id, {
    name: `Worker Pipeline ${suffix}`,
    stageName: "pytest",
    test_path: "tests/",
    args: ["-s"],
    timeout_seconds: 300,
  });

  await loginViaUi(page);
  await page.goto(`/projects/${project.id}`);
  await expect(page.getByRole("heading", { level: 1, name: project.name })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Trigger Run" }).click();
  await expect(page.getByRole("heading", { name: "Trigger Run" })).toBeVisible();

  const comboboxes = page.getByRole("combobox");
  await comboboxes.nth(0).click();
  await page.getByRole("option", { name: pipeline.name }).click();
  await comboboxes.nth(1).click();
  await page.getByRole("option", { name: environment.name }).click();
  await page.getByRole("button", { name: "Run Pipeline" }).click();

  await expect(page).toHaveURL(/\/runs\/[^/]+$/);
  const runId = runIdFromPage(page);
  await expect(page.getByRole("heading", { level: 1, name: pipeline.name })).toBeVisible();
  await page.getByRole("tab", { name: /Logs/ }).click();
  await expect(page.getByText("Execution Logs")).toBeVisible();

  const terminalRun = await waitForRunTerminal(request, login.token, runId);
  expect(terminalRun.status).toBe("done");
  expect(terminalRun.summary).toEqual({
    total: 1,
    passed: 1,
    failed: 0,
    skipped: 0,
    error: 0,
    pass_rate: 1,
  });

  const results = await waitForRunResults(request, login.token, runId);
  expect(results.map((result) => ({ name: result.name, status: result.status }))).toEqual([
    { name: testCaseName, status: "passed" },
  ]);
  const artifacts = await waitForArtifacts(request, login.token, runId);
  expect(artifacts.map((artifact) => ({ name: artifact.name, type: artifact.type }))).toEqual([
    { name: "junit.xml", type: "junit" },
  ]);
  await waitForArchivedLogsContaining(request, login.token, runId, [
    "Repository cloned successfully",
    "Starting stage: pytest",
    "Uploaded artifact: junit.xml",
    "Run completed: done",
  ]);

  await loginViaUi(page);
  await page.goto(`/runs/${runId}`);
  await expect(page.getByRole("heading", { level: 1, name: pipeline.name })).toBeVisible({
    timeout: 30_000,
  });
  await expectPassedResultRow(page, testCaseName, 60_000);
  await page.getByRole("tab", { name: /Logs/ }).click();
  await expect(page.getByText("Run completed: done")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("tab", { name: /Test Results/ }).click();
  await expectPassedResultRow(page, testCaseName);
  await page.getByRole("tab", { name: /Artifacts/ }).click();
  await expect(page.getByRole("heading", { name: "junit.xml" })).toBeVisible();
  await expect(page.getByText(/^\d+\.\d{2} MB • junit$/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Download junit.xml" })).toBeVisible();
});
