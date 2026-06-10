import type {
  Project,
  Pipeline,
  Environment,
  RunResponse,
  TestResult,
  Artifact,
  ApiTokenListItem,
} from "../../types/api";

// 辅助函数：生成唯一 ID
export const genId = (prefix = "test") => `${prefix}-${Math.random().toString(36).substr(2, 9)}`;

// Project fixtures
export const createMockProject = (overrides?: Partial<Project>): Project => ({
  id: genId("proj"),
  tenant_id: "tenant-1",
  name: "Test Project",
  slug: "test-project",
  description: "A test project",
  git_url: "https://github.com/test/repo",
  git_auth_method: "none",
  credential_id: null,
  default_branch: "main",
  root_path: ".",
  shallow_clone: true,
  default_env_id: null,
  settings: {},
  silent_windows: [],
  status: "active",
  created_by: "user-1",
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

export const mockProjects: Project[] = [
  createMockProject({ id: "proj-1", name: "Project Alpha", slug: "project-alpha" }),
  createMockProject({ id: "proj-2", name: "Project Beta", slug: "project-beta" }),
  createMockProject({ id: "proj-3", name: "Project Gamma", slug: "project-gamma" }),
];

// Pipeline fixtures
export const createMockPipeline = (overrides?: Partial<Pipeline>): Pipeline => ({
  id: genId("pipe"),
  project_id: "proj-1",
  name: "Test Pipeline",
  stages: [],
  selector: {
    include_paths: [],
    exclude_paths: [],
    tags: [],
    expression: null,
    regex: null,
    on_empty: "warn",
  },
  trigger_config: {
    type: "manual",
    dedup_window_seconds: null,
    source: {},
    conditions: {},
    target: {},
  },
  collectors: [],
  timeout_seconds: 3600,
  retry_policy: null,
  enabled: true,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

export const mockPipelines: Pipeline[] = [
  createMockPipeline({ id: "pipe-1", name: "main-pipeline", project_id: "proj-1" }),
  createMockPipeline({ id: "pipe-2", name: "smoke-tests", project_id: "proj-1" }),
];

// Environment fixtures
export const createMockEnvironment = (overrides?: Partial<Environment>): Environment => ({
  id: genId("env"),
  project_id: "proj-1",
  name: "Test Environment",
  base_image: "python:3.11",
  setup_script: null,
  memory_mb: 2048,
  cpu_cores: 2,
  disk_mb: null,
  max_artifact_size_mb: 100,
  max_artifacts_count: 50,
  network_policy: "allow",
  variables: {},
  cache_key: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

export const mockEnvironments: Environment[] = [
  createMockEnvironment({ id: "env-1", name: "development" }),
  createMockEnvironment({ id: "env-2", name: "staging" }),
];

// Run fixtures
export const createMockRun = (overrides?: Partial<RunResponse>): RunResponse => ({
  id: genId("run"),
  tenant_id: "tenant-1",
  project_id: "proj-1",
  pipeline_id: "pipe-1",
  pipeline_name: "main-pipeline",
  environment_id: "env-1",
  status: "queued",
  trigger_type: "manual",
  priority: 1,
  triggered_by: "user-1",
  git_ref: "main",
  git_sha: "abc123",
  attempt: 1,
  started_at: null,
  finished_at: null,
  duration_ms: null,
  summary: null,
  error_message: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

export const mockRunRunning = createMockRun({
  id: "run-running",
  status: "running",
  started_at: "2024-01-01T00:05:00Z",
});

export const mockRunDoneSuccess = createMockRun({
  id: "run-success",
  status: "done",
  started_at: "2024-01-01T00:05:00Z",
  finished_at: "2024-01-01T00:10:00Z",
  duration_ms: 300000,
  summary: { total: 10, passed: 10, failed: 0, skipped: 0, error: 0, pass_rate: 1.0 },
});

export const mockRunDoneFailed = createMockRun({
  id: "run-failed",
  status: "done",
  started_at: "2024-01-01T00:05:00Z",
  finished_at: "2024-01-01T00:10:00Z",
  duration_ms: 300000,
  summary: { total: 10, passed: 8, failed: 2, skipped: 0, error: 0, pass_rate: 0.8 },
});

export const mockRunCancelled = createMockRun({
  id: "run-cancelled",
  status: "cancelled",
  started_at: "2024-01-01T00:05:00Z",
  finished_at: "2024-01-01T00:07:00Z",
  duration_ms: 120000,
});

// TestResult fixtures
export const createMockTestResult = (overrides?: Partial<TestResult>): TestResult => ({
  id: genId("test"),
  run_id: "run-1",
  suite: "test.suite",
  name: "test_example",
  status: "passed",
  duration_ms: 1000,
  error_message: null,
  stack_trace: null,
  tags: [],
  metadata: {},
  ...overrides,
});

export const mockTestResults: TestResult[] = [
  createMockTestResult({ id: "test-1", name: "test_login", status: "passed" }),
  createMockTestResult({ id: "test-2", name: "test_logout", status: "passed" }),
  createMockTestResult({ id: "test-3", name: "test_validation", status: "failed", error_message: "Assertion failed" }),
];

// Artifact fixtures
export const createMockArtifact = (overrides?: Partial<Artifact>): Artifact => ({
  id: genId("art"),
  run_id: "run-1",
  type: "junit",
  name: "junit.xml",
  storage_path: "/artifacts/run-1/junit.xml",
  size_bytes: 1024,
  mime_type: "application/xml",
  expires_at: null,
  created_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

export const mockArtifacts: Artifact[] = [
  createMockArtifact({ id: "art-1", type: "junit", name: "junit.xml" }),
  createMockArtifact({ id: "art-2", type: "html", name: "report.html", mime_type: "text/html" }),
];

// ApiToken fixtures
export const createMockApiToken = (overrides?: Partial<ApiTokenListItem>): ApiTokenListItem => ({
  token_id: genId("token"),
  name: "Test Token",
  scopes: ["run.read"],
  expires_at: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString(),
  last_used_at: null,
  is_revoked: false,
  created_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

export const mockApiTokens: ApiTokenListItem[] = [
  createMockApiToken({ token_id: "token-1", name: "CI Token", scopes: ["run.read", "run.write"] }),
  createMockApiToken({ token_id: "token-2", name: "Read Only", scopes: ["run.read"] }),
];
