import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Pipeline, PipelineUpdatePayload } from "../types/api";

export function usePipeline(projectId: string, id: string) {
  return useQuery({
    queryKey: ["projects", projectId, "pipelines", id],
    queryFn: async () => {
      const { data } = await api.get<Pipeline>(`/projects/${projectId}/pipelines/${id}`);
      return data;
    },
    enabled: !!projectId && !!id,
  });
}

export function useUpdatePipeline(id: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pipeline: PipelineUpdatePayload) => {
      const { data } = await api.put<Pipeline>(`/projects/${projectId}/pipelines/${id}`, pipeline);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "pipelines", id] });
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "pipelines"] });
    },
  });
}

export function useDeletePipeline(id: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.delete(`/projects/${projectId}/pipelines/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "pipelines"] });
    },
  });
}
