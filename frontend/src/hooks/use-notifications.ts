import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { NotificationRule } from "../types/api";

export function useNotificationRules(projectId: string) {
  return useQuery({
    queryKey: ["projects", projectId, "notification-rules"],
    queryFn: async () => {
      const { data } = await api.get<NotificationRule[]>(
        `/projects/${projectId}/notification-rules`
      );
      return data;
    },
    enabled: !!projectId,
    staleTime: 30_000,
  });
}

export function useCreateNotificationRule(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      rule: Omit<NotificationRule, "id" | "project_id" | "created_at">
    ) => {
      const { data } = await api.post<NotificationRule>(
        `/projects/${projectId}/notification-rules`,
        rule
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", projectId, "notification-rules"],
      });
    },
  });
}

export function useUpdateNotificationRule(projectId: string, ruleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      rule: Partial<Omit<NotificationRule, "id" | "project_id" | "created_at">>
    ) => {
      const { data } = await api.put<NotificationRule>(
        `/projects/${projectId}/notification-rules/${ruleId}`,
        rule
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", projectId, "notification-rules"],
      });
    },
  });
}

export function useDeleteNotificationRule(projectId: string, ruleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.delete(
        `/projects/${projectId}/notification-rules/${ruleId}`
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", projectId, "notification-rules"],
      });
    },
  });
}
