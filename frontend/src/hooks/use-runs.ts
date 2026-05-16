import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Run, PaginatedResponse, TestResult, Artifact } from "../types/api";

export function useRuns(params?: { page?: number; per_page?: number; status?: string; sort?: string }) {
  return useQuery({
    queryKey: ["runs", params],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Run>>("/runs", { params });
      return data;
    },
  });
}

export function useRun(id: string) {
  return useQuery({
    queryKey: ["runs", id],
    queryFn: async () => {
      const { data } = await api.get<Run>(`/runs/${id}`);
      return data;
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
    mutationFn: async (runData: { pipeline_id: string; branch?: string; env_overrides?: Record<string, string>; params?: Record<string, any> }) => {
      const { data } = await api.post<Run>("/runs", runData);
      return data;
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
      const { data } = await api.post<Run>(`/runs/${id}/cancel`, { reason });
      return data;
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
      const { data } = await api.get<Artifact[]>(`/runs/${id}/artifacts`);
      return data;
    },
    enabled: !!id,
  });
}
