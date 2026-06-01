import { defineConfig, devices, type PlaywrightTestConfig } from "@playwright/test";
import { applyQapE2eEnv } from "./tests/e2e/qap-env";

applyQapE2eEnv();

const useSystemChrome = process.env.PLAYWRIGHT_USE_SYSTEM_CHROME === "1";
const reporter: PlaywrightTestConfig["reporter"] = process.env.CI
  ? [
      ["list"],
      ["html", { outputFolder: "artifacts/e2e/playwright-report", open: "never" }],
      ["junit", { outputFile: "artifacts/e2e/playwright-results.xml" }],
      ["json", { outputFile: "artifacts/e2e/playwright-run.json" }],
    ]
  : "list";

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  reporter,
  globalSetup: "./tests/e2e/global-setup.ts",
  globalTeardown: "./tests/e2e/global-teardown.ts",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(useSystemChrome ? { channel: "chrome" } : {}),
      },
    },
  ],
  webServer: [
    {
      name: "backend",
      command: "sh -c 'docker compose up -d postgres redis minio >/dev/null && until nc -z 127.0.0.1 5432 && nc -z 127.0.0.1 6379; do sleep 1; done && .venv/bin/python -m uvicorn qaplatform.main:create_app --factory --host 0.0.0.0 --port 8000 --app-dir src'",
      url: "http://localhost:8000/health",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      name: "frontend",
      command: "cd frontend && npm run dev -- --host 0.0.0.0 --port 5173",
      url: "http://localhost:5173",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
