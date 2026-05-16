import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Pipeline } from "../types/api";

export function usePipeline(id: string) {
  return useQuery({
    queryKey: ["pipelines", id],
    queryFn: async () => {
      const { data } = await api.get<Pipeline>(`/pipelines/${id}`);
      return data;
    },
    enabled: !!id,
  });
}

export function useUpdatePipeline(id: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pipeline: Partial<Pipeline>) => {
      const { data } = await api.put<Pipeline>(`/pipelines/${id}`, pipeline);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipelines", id] });
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "pipelines"] });
    },
  });
}

export function useDeletePipeline(id: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.delete(`/pipelines/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "pipelines"] });
    },
  });
}
