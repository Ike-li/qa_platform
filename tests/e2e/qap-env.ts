const QAP_E2E_DEFAULT_ENV = {
  QAP_DATABASE_URL: "postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform",
  QAP_REDIS_URL: "redis://localhost:6379/0",
  QAP_S3_ENDPOINT: "http://localhost:9000",
  QAP_S3_ACCESS_KEY: "minioadmin",
  QAP_S3_SECRET_KEY: "minioadmin",
  QAP_S3_BUCKET: "qa-platform",
  QAP_S3_REGION: "us-east-1",
  QAP_JWT_SECRET: "ci-test-jwt-secret-not-for-production-use",
  QAP_ENCRYPTION_KEY: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
} as const;

export function qapE2eEnv(base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...base };
  for (const [key, value] of Object.entries(QAP_E2E_DEFAULT_ENV)) {
    env[key] = base[key] || value;
  }
  return env;
}

export function applyQapE2eEnv(base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  for (const [key, value] of Object.entries(QAP_E2E_DEFAULT_ENV)) {
    if (!base[key]) {
      base[key] = value;
    }
  }
  return base;
}

export function qapWorkerEnv(base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env = qapE2eEnv(base);
  return {
    ...env,
    PYTHONPATH: ["src", env.PYTHONPATH].filter(Boolean).join(":"),
    QAP_WORKER_QUEUE: env.QAP_WORKER_QUEUE || "queue:medium",
    QAP_WORKER_MAX_JOBS: env.QAP_WORKER_MAX_JOBS || "1",
  };
}
