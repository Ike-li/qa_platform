import fs from "node:fs";

const WORKER_PID_FILE = "artifacts/e2e/worker.pid";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function killProcessGroup(pid: number, signal: NodeJS.Signals) {
  try {
    process.kill(-pid, signal);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") {
      throw error;
    }
  }
}

export default async function globalTeardown() {
  if (process.env.QAP_E2E_WORKER !== "1" || !fs.existsSync(WORKER_PID_FILE)) {
    return;
  }

  const pid = Number(fs.readFileSync(WORKER_PID_FILE, "utf8").trim());
  if (!Number.isFinite(pid) || pid <= 0) {
    fs.rmSync(WORKER_PID_FILE, { force: true });
    return;
  }

  killProcessGroup(pid, "SIGTERM");
  await sleep(2000);
  killProcessGroup(pid, "SIGKILL");
  fs.rmSync(WORKER_PID_FILE, { force: true });
}
