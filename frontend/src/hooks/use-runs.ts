import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type {
  Run,
  RunStatus,
  BackendRunStatus,
  RunResponse,
  PaginatedResponse,
  TestResult,
  Artifact,
  RunLogEntry,
  TriggerRunPayload
} from "../types/api";

const RUN_STATUSES: readonly RunStatus[] = [
  "queued",
  "preparing",
  "running",
  "collecting",
  "passed",
  "failed",
  "cancelled",
  "timed_out",
  "unknown",
];
const BACKEND_TERMINAL_RUN_STATUSES: readonly BackendRunStatus[] = [
  "done",
  "failed",
  "cancelled",
  "timeout",
];

function isRunStatus(value: string): value is RunStatus {
  return (RUN_STATUSES as readonly string[]).includes(value);
}

function normalizeRun(run: RunResponse): Run {
  const summary = run.summary ?? {};
  const passed = summary.passed ?? 0;
  const failed = summary.failed ?? 0;
  const skipped = summary.skipped ?? 0;
  const error = summary.error ?? 0;
  const total = summary.total ?? passed + failed + skipped + error;
  const backendStatus = String(run.status);
  let rawStatus: string;
  if (backendStatus === "done") {
    if (failed > 0 || error > 0) {
      rawStatus = "failed";
    } else if (total > 0) {
      rawStatus = "passed";
    } else {
      rawStatus = "unknown";
    }
  } else if (backendStatus === "timeout") {
    rawStatus = "timed_out";
  } else {
    rawStatus = backendStatus;
  }
  const status = isRunStatus(rawStatus) ? rawStatus : "unknown";

  return {
    id: run.id,
    project_id: run.project_id,
    pipeline_id: run.pipeline_id,
    pipeline_name: run.pipeline_name || `Pipeline ${run.pipeline_id.slice(0, 8)}`,
    environment_id: run.environment_id,
    status,
    is_terminal: BACKEND_TERMINAL_RUN_STATUSES.includes(run.status),
    branch: run.git_ref || "-",
    git_sha: run.git_sha,
    triggered_by: run.triggered_by,
    trigger_type: run.trigger_type,
    started_at: run.started_at,
    finished_at: run.finished_at,
    duration_seconds: run.duration_ms == null ? null : run.duration_ms / 1000,
    total_tests: total,
    passed_tests: passed,
    failed_tests: failed,
    skipped_tests: skipped,
    error_message: run.error_message,
    priority: run.priority ?? 1,
    created_at: run.created_at,
    updated_at: run.updated_at,
  };
}

export function useRuns(params?: { page?: number; per_page?: number; status?: string; sort?: string; enabled?: boolean }) {
  const { enabled, ...apiParams } = params ?? {};
  return useQuery({
    queryKey: ["runs", apiParams],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<RunResponse>>("/runs", { params: apiParams });
      return { ...data, data: data.data.map(normalizeRun) };
    },
    enabled,
  });
}

export function useRun(id: string) {
  return useQuery({
    queryKey: ["runs", id],
    queryFn: async () => {
      const { data } = await api.get<RunResponse>(`/runs/${id}`);
      return normalizeRun(data);
    },
    enabled: !!id,
    refetchInterval: (query) => {
      return query.state.data?.is_terminal ? false : 5000;
    },
  });
}

export function useTriggerRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (runData: TriggerRunPayload) => {
      const { data } = await api.post<RunResponse>("/runs", {
        pipeline_id: runData.pipeline_id,
        git_ref: runData.branch,
        git_sha: runData.git_sha,
        environment_id: runData.environment_id,
        priority: runData.priority ?? 1,
      });
      return normalizeRun(data);
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["projects", data.project_id, "runs"] });
    },
  });
}

export function useCancelRun(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (reason?: string) => {
      const { data } = await api.post<RunResponse>(`/runs/${id}/cancel`, { reason });
      return normalizeRun(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", id] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useRunResults(id: string, params?: { page?: number; per_page?: number }) {
  return useQuery({
    queryKey: ["runs", id, "results", params],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<TestResult>>(`/runs/${id}/results`, { params });
      return data;
    },
    enabled: !!id,
  });
}

export function useRunArtifacts(id: string) {
  return useQuery({
    queryKey: ["runs", id, "artifacts"],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Artifact>>(`/runs/${id}/artifacts`);
      return data.data;
    },
    enabled: !!id,
  });
}

export function useArchivedRunLogs(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["runs", id, "logs", "archive"],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<RunLogEntry>>(
        `/runs/${id}/logs/archive`,
        { params: { per_page: 1000 } },
      );
      return data;
    },
    enabled: !!id && enabled,
    retry: false,
    staleTime: 30_000,
  });
}
