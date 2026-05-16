import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Run, PaginatedResponse, TestResult, Artifact } from "../types/api";

type BackendRun = Omit<Run, "pipeline_name" | "branch" | "duration_seconds" | "total_tests" | "passed_tests" | "failed_tests" | "skipped_tests" | "env_overrides" | "params"> & {
  tenant_id?: string;
  environment_id?: string;
  git_ref?: string;
  duration_ms?: number | null;
  summary?: {
    total?: number;
    passed?: number;
    failed?: number;
    skipped?: number;
  } | null;
};

function unwrapPaginated<T>(value: T[] | PaginatedResponse<T>): T[] {
  return Array.isArray(value) ? value : value.data;
}

function normalizeRun(run: Run | BackendRun): Run {
  const backendRun = run as BackendRun;
  const summary = backendRun.summary ?? {};
  const backendStatus = String(backendRun.status);
  const status = backendStatus === "done"
    ? "passed"
    : backendStatus === "timeout"
      ? "timed_out"
      : backendStatus;

  return {
    ...run,
    status: status as Run["status"],
    pipeline_name: (run as Run).pipeline_name ?? `Pipeline ${run.pipeline_id.slice(0, 8)}`,
    branch: (run as Run).branch ?? backendRun.git_ref ?? "-",
    env_overrides: (run as Run).env_overrides ?? {},
    params: (run as Run).params ?? {},
    duration_seconds: (run as Run).duration_seconds ?? (
      backendRun.duration_ms == null ? null : backendRun.duration_ms / 1000
    ),
    total_tests: (run as Run).total_tests ?? summary.total ?? 0,
    passed_tests: (run as Run).passed_tests ?? summary.passed ?? 0,
    failed_tests: (run as Run).failed_tests ?? summary.failed ?? 0,
    skipped_tests: (run as Run).skipped_tests ?? summary.skipped ?? 0,
    worker_id: (run as Run).worker_id ?? null,
    cancel_requested_at: (run as Run).cancel_requested_at ?? null,
  };
}

export function useRuns(params?: { page?: number; per_page?: number; status?: string; sort?: string }) {
  return useQuery({
    queryKey: ["runs", params],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Run | BackendRun>>("/runs", { params });
      return { ...data, data: data.data.map(normalizeRun) };
    },
  });
}

export function useRun(id: string) {
  return useQuery({
    queryKey: ["runs", id],
    queryFn: async () => {
      const { data } = await api.get<Run | BackendRun>(`/runs/${id}`);
      return normalizeRun(data);
    },
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "passed" || status === "failed" || status === "cancelled" || status === "timed_out" ? false : 5000;
    },
  });
}

export function useTriggerRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (runData: { pipeline_id: string; branch?: string; env_overrides?: Record<string, string>; params?: Record<string, unknown> }) => {
      const { data } = await api.post<Run | BackendRun>("/runs", {
        pipeline_id: runData.pipeline_id,
        git_ref: runData.branch,
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
      const { data } = await api.post<Run | BackendRun>(`/runs/${id}/cancel`, { reason });
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
      const { data } = await api.get<Artifact[] | PaginatedResponse<Artifact>>(`/runs/${id}/artifacts`);
      return unwrapPaginated(data);
    },
    enabled: !!id,
  });
}
