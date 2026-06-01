export interface SilentWindow {
  start_at: string;
  end_at: string;
  reason: string;
}

export interface Project {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  description: string | null;
  git_url: string;
  git_auth_method: GitAuthMethod;
  credential_id: string | null;
  default_branch: string;
  root_path: string;
  shallow_clone: boolean;
  default_env_id: string | null;
  settings: Record<string, unknown>;
  silent_windows: SilentWindow[];
  status: "active" | "archived";
  created_by: string;
  created_at: string;
  updated_at: string;
}

export type GitAuthMethod = "none" | "token" | "ssh_key";

export interface ProjectCreatePayload {
  name: string;
  slug: string;
  description?: string | null;
  git_url: string;
  git_auth_method?: GitAuthMethod;
  credential_id?: string | null;
  default_branch?: string;
  root_path?: string;
  shallow_clone?: boolean;
  default_env_id?: string | null;
  settings?: Record<string, unknown>;
}

export type ProjectUpdatePayload = Partial<
  Pick<
    ProjectCreatePayload,
    | "name"
    | "description"
    | "git_url"
    | "git_auth_method"
    | "credential_id"
    | "default_branch"
    | "root_path"
    | "shallow_clone"
    | "default_env_id"
    | "settings"
  >
> & {
  silent_windows?: SilentWindow[];
  status?: "active" | "archived";
};

export interface PipelineStage {
  name: string;
  plugin: string;
  config: Record<string, unknown>;
  continue_on_error: boolean;
  phase: "prepare" | "execute" | "collect" | "notify" | null;
}

export interface PipelineSelector {
  include_paths: string[];
  exclude_paths: string[];
  tags: string[];
  expression: string | null;
  regex: string | null;
  on_empty: "fail" | "skip" | "warn";
}

export interface PipelineTriggerConfig {
  type: string;
  dedup_window_seconds: number | null;
  source: Record<string, unknown>;
  conditions: Record<string, unknown>;
  target: Record<string, unknown>;
}

export interface PipelineRetryPolicy {
  max_attempts: number;
  retry_on: string[];
  backoff_seconds: number;
  scope: "pipeline" | "stage";
}

export interface PipelineCollector {
  plugin: string;
  config: Record<string, unknown>;
  enabled: boolean;
}

export interface Pipeline {
  id: string;
  project_id: string;
  name: string;
  stages: PipelineStage[];
  selector: PipelineSelector;
  trigger_config: PipelineTriggerConfig;
  collectors: PipelineCollector[];
  timeout_seconds: number;
  retry_policy: PipelineRetryPolicy | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface PipelineCreatePayload {
  name: string;
  stages?: PipelineStage[];
  selector?: PipelineSelector;
  trigger_config?: PipelineTriggerConfig;
  collectors?: PipelineCollector[];
  timeout_seconds?: number;
  retry_policy?: PipelineRetryPolicy | null;
  enabled?: boolean;
}

export type PipelineUpdatePayload = Partial<PipelineCreatePayload>;

export type NetworkPolicy = "allow" | "deny" | "restricted";

export interface EnvironmentResponse {
  id: string;
  project_id: string;
  name: string;
  base_image: string;
  setup_script: string | null;
  memory_mb: number;
  cpu_cores: number;
  disk_mb: number | null;
  max_artifact_size_mb: number;
  max_artifacts_count: number;
  network_policy: NetworkPolicy;
  env_vars: Record<string, string>;
  cache_key: string | null;
  created_at: string;
}

export interface Environment extends Omit<EnvironmentResponse, "env_vars"> {
  variables: Record<string, string>;
  updated_at?: string;
}

export interface CreateEnvironmentPayload {
  name: string;
  base_image: string;
  setup_script?: string | null;
  memory_mb?: number;
  cpu_cores?: number;
  disk_mb?: number | null;
  max_artifact_size_mb?: number;
  max_artifacts_count?: number;
  network_policy?: NetworkPolicy;
  env_vars?: Record<string, string>;
  cache_key?: string | null;
}

export type UpdateEnvironmentPayload = Partial<CreateEnvironmentPayload>;

export type BackendRunStatus =
  | "queued"
  | "preparing"
  | "running"
  | "collecting"
  | "done"
  | "failed"
  | "timeout"
  | "cancelled";

export type RunStatus =
  | "queued"
  | "preparing"
  | "running"
  | "collecting"
  | "passed"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "unknown";

export interface RunSummary {
  total?: number;
  passed?: number;
  failed?: number;
  skipped?: number;
  error?: number;
  pass_rate?: number;
  [key: string]: unknown;
}

export interface RunResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  pipeline_id: string;
  pipeline_name: string;
  environment_id: string;
  status: BackendRunStatus;
  trigger_type: string;
  priority: number;
  triggered_by: string | null;
  git_ref: string;
  git_sha: string | null;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  summary: RunSummary | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Run {
  id: string;
  project_id: string;
  pipeline_id: string;
  pipeline_name: string;
  environment_id: string;
  status: RunStatus;
  is_terminal: boolean;
  branch: string;
  git_sha: string | null;
  triggered_by: string | null;
  trigger_type: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  skipped_tests: number;
  error_message: string | null;
  priority: number;
  created_at: string;
  updated_at: string;
}

export interface TriggerRunPayload {
  pipeline_id: string;
  branch?: string;
  git_sha?: string;
  environment_id?: string;
  priority?: number;
}

export interface TestResult {
  id: string;
  run_id: string;
  suite: string;
  name: string;
  status: TestResultStatus;
  duration_ms: number;
  error_message: string | null;
  stack_trace: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
}

export type TestResultStatus = "passed" | "failed" | "skipped" | "error" | "xfail";

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

export interface RunLogEntry {
  stream: string;
  line: string;
}

export type NotificationConditionField =
  | "status"
  | "pass_rate"
  | "failed"
  | "consecutive_failures";

export interface NotificationCondition {
  field: NotificationConditionField;
  operator: "eq" | "ne" | "lt" | "gt" | "lte" | "gte";
  value: string | number | boolean;
}

export interface NotificationConditionGroup {
  all?: NotificationConditionExpression[];
  any?: NotificationConditionExpression[];
}

export interface NotificationConditionInputGroup {
  all?: NotificationConditionInputExpression[];
  any?: NotificationConditionInputExpression[];
}

export interface NotificationInvalidCondition {
  invalid: true;
  reason: string;
  raw_field?: string | null;
  raw_operator?: string | null;
}

export type NotificationConditionExpression =
  | NotificationCondition
  | NotificationConditionGroup
  | NotificationInvalidCondition;

export type NotificationConditionInputExpression =
  | NotificationCondition
  | NotificationConditionInputGroup;

export type NotificationChannelType = "email" | "webhook" | "dingtalk" | "wecom";
export type NotificationChannelConfigValue = string | string[];

export interface NotificationChannel {
  type: NotificationChannelType;
  config: Record<string, NotificationChannelConfigValue>;
  template?: string | null;
}

export interface NotificationRule {
  id: string;
  project_id: string;
  name: string;
  enabled: boolean;
  conditions: NotificationConditionExpression[];
  channels: NotificationChannel[];
  template: string | null;
  created_at: string;
}

export interface NotificationRuleCreatePayload {
  name: string;
  enabled: boolean;
  conditions: NotificationConditionInputExpression[];
  channels: NotificationChannel[];
  template: string | null;
}

export type NotificationRuleUpdatePayload = Partial<NotificationRuleCreatePayload>;

export interface ApiTokenListItem {
  token_id: string;
  name: string;
  scopes: string[];
  expires_at: string;
  last_used_at: string | null;
  is_revoked: boolean;
  created_at: string;
}

export interface ApiTokenResponse {
  token_id: string;
  token: string | null;
  name: string;
  scopes: string[];
  expires_at: string;
  created_at: string;
}

export interface CreateApiTokenPayload {
  name: string;
  scopes?: string[];
  expires_days?: number;
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

export interface TestHistoryPoint {
  run_id: string;
  run_created_at: string;
  run_status: BackendRunStatus;
  status: TestResultStatus;
  duration_ms: number | null;
  error_message: string | null;
  git_ref: string | null;
}
