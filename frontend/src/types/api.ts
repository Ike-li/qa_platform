export interface Project {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  description: string | null;
  git_url: string;
  git_auth_method: "none" | "token" | "ssh_key";
  credential_id: string | null;
  default_branch: string;
  root_path: string;
  shallow_clone: boolean;
  default_env_id: string | null;
  settings: Record<string, unknown>;
  status: "active" | "archived";
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface PipelineStage {
  name: string;
  command: string;
  timeout_seconds?: number;
  env?: Record<string, string>;
  depends_on?: string[];
}

export interface Pipeline {
  id: string;
  project_id: string;
  name: string;
  stages: PipelineStage[];
  selector: { framework: string; pattern: string; tags?: string[] };
  trigger_config: { on_push: boolean; on_schedule?: string; branches?: string[] };
  timeout_seconds: number;
  retry_policy: { max_retries: number; backoff: "fixed" | "exponential" } | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface Environment {
  id: string;
  project_id: string;
  name: string;
  variables: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export type RunStatus = "queued" | "preparing" | "running" | "collecting" | "passed" | "failed" | "cancelled" | "timed_out";

export interface Run {
  id: string;
  project_id: string;
  pipeline_id: string;
  pipeline_name: string;
  status: RunStatus;
  branch: string;
  git_sha: string | null;
  triggered_by: string;
  trigger_type: "manual" | "schedule" | "webhook";
  env_overrides: Record<string, string>;
  params: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  skipped_tests: number;
  error_message: string | null;
  worker_id: string | null;
  cancel_requested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TestResult {
  id: string;
  run_id: string;
  suite: string;
  name: string;
  status: "passed" | "failed" | "skipped" | "error";
  duration_ms: number;
  error_message: string | null;
  stack_trace: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
}

export interface Artifact {
  id: string;
  run_id: string;
  type: string;
  name: string;
  storage_path: string;
  size_bytes: number;
  mime_type: string;
  expires_at: string | null;
  created_at: string;
}

export interface NotificationCondition {
  field: "status" | "pass_rate" | "failed";
  op: "eq" | "ne" | "lt" | "gt" | "lte" | "gte";
  value: string | number;
}

export interface NotificationChannel {
  type: "email" | "webhook";
  config: Record<string, string>;
}

export interface NotificationRule {
  id: string;
  project_id: string;
  name: string;
  enabled: boolean;
  conditions: NotificationCondition[];
  channels: NotificationChannel[];
  template: string | null;
  created_at: string;
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  per_page: number;
}

export interface TrendDataPoint {
  date: string;
  total_runs: number;
  passed_runs: number;
  failed_runs: number;
  pass_rate: number;
}

export interface FlakyTest {
  suite: string;
  name: string;
  total_runs: number;
  failed_count: number;
  passed_count: number;
  flaky_rate: number;
}
