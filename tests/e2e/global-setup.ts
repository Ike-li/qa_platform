import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import type { FullConfig } from "@playwright/test";

const COMPOSE_SERVICES = ["postgres", "redis", "minio"] as const;
const PYTHON = ".venv/bin/python";
const ARTIFACT_DIR = "artifacts/e2e";
const WORKER_PID_FILE = `${ARTIFACT_DIR}/worker.pid`;
const WORKER_LOG_FILE = `${ARTIFACT_DIR}/worker.log`;

async function canConnect(port: number, host = "127.0.0.1", timeoutMs = 1000): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    const done = (result: boolean) => {
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

function run(command: string, args: string[], env: NodeJS.ProcessEnv = process.env) {
  execFileSync(command, args, {
    cwd: process.cwd(),
    env,
    stdio: "inherit",
  });
}

function compose(args: string[]) {
  run("docker", ["compose", ...args]);
}

function serviceHealth(service: string): string {
  const containerId = execFileSync("docker", ["compose", "ps", "-q", service], {
    cwd: process.cwd(),
    encoding: "utf8",
  }).trim();

  if (!containerId) {
    return "missing";
  }

  return execFileSync("docker", [
    "inspect",
    "-f",
    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
    containerId,
  ], {
    cwd: process.cwd(),
    encoding: "utf8",
  }).trim();
}

async function waitForHealthy(timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const states = COMPOSE_SERVICES.map((service) => [service, serviceHealth(service)] as const);
    if (states.every(([, state]) => state === "healthy" || state === "running")) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  const states = COMPOSE_SERVICES.map((service) => `${service}:${serviceHealth(service)}`).join(", ");
  throw new Error(`Timed out waiting for docker compose services to become healthy: ${states}`);
}

async function ensureInfrastructure() {
  const postgresReady = await canConnect(5432);
  const redisReady = await canConnect(6379);

  if (!postgresReady || !redisReady) {
    compose(["up", "-d", ...COMPOSE_SERVICES]);
  } else if (serviceHealth("minio") !== "healthy") {
    compose(["up", "-d", "minio"]);
  }

  await waitForHealthy();
  compose(["run", "--rm", "minio-init"]);
}

function qapWorkerEnv(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    PYTHONPATH: ["src", process.env.PYTHONPATH].filter(Boolean).join(":"),
    QAP_WORKER_QUEUE: "queue:medium",
    QAP_WORKER_MAX_JOBS: process.env.QAP_WORKER_MAX_JOBS || "1",
    QAP_DATABASE_URL:
      process.env.QAP_DATABASE_URL ||
      "postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform",
    QAP_REDIS_URL: process.env.QAP_REDIS_URL || "redis://localhost:6379/0",
    QAP_S3_ENDPOINT: process.env.QAP_S3_ENDPOINT || "http://localhost:9000",
    QAP_S3_ACCESS_KEY: process.env.QAP_S3_ACCESS_KEY || "minioadmin",
    QAP_S3_SECRET_KEY: process.env.QAP_S3_SECRET_KEY || "minioadmin",
    QAP_S3_BUCKET: process.env.QAP_S3_BUCKET || "qa-platform",
    QAP_JWT_SECRET: process.env.QAP_JWT_SECRET || "ci-test-jwt-secret-not-for-production-use",
    QAP_ENCRYPTION_KEY:
      process.env.QAP_ENCRYPTION_KEY ||
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  };
}

async function startWorkerIfRequested() {
  if (process.env.QAP_E2E_WORKER !== "1") {
    return;
  }

  fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
  const logFd = fs.openSync(WORKER_LOG_FILE, "a");
  const worker = spawn(".venv/bin/arq", ["qaplatform.worker.settings.WorkerSettings"], {
    cwd: process.cwd(),
    detached: true,
    env: qapWorkerEnv(),
    stdio: ["ignore", logFd, logFd],
  });
  fs.closeSync(logFd);

  await new Promise<void>((resolve, reject) => {
    worker.once("error", reject);
    setTimeout(resolve, 3000);
  });

  if (!worker.pid || worker.exitCode !== null) {
    throw new Error(`E2E worker failed to start; see ${WORKER_LOG_FILE}`);
  }

  fs.writeFileSync(WORKER_PID_FILE, `${worker.pid}\n`, "utf8");
  worker.unref();
}

export default async function globalSetup(_config: FullConfig) {
  await ensureInfrastructure();

  run(PYTHON, ["-m", "alembic", "upgrade", "head"]);
  run(PYTHON, ["scripts/seed_admin.py"], {
    ...process.env,
    ADMIN_USERNAME: "admin",
    ADMIN_PASSWORD: process.env.E2E_ADMIN_PASSWORD || "admin123",
    ADMIN_EMAIL: "admin@qaplatform.local",
  });
  await startWorkerIfRequested();
}
