import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";

export interface ShareToken {
  id: string;
  share_url: string;
  token: string;
  expires_at: string;
  max_access_count: number | null;
  access_count: number;
  is_expired: boolean;
  created_by: string;
  created_at: string;
}

export interface CreateShareTokenRequest {
  expires_in_days?: number;
  max_access_count?: number | null;
}

export interface CreateShareTokenResponse {
  id: string;
  share_url: string;
  token: string;
  expires_at: string;
  max_access_count: number | null;
}

/**
 * Hook to create a share token for a run's Allure report
 */
export function useCreateShareToken(runId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: CreateShareTokenRequest) => {
      const response = await api.post<CreateShareTokenResponse>(
        `/api/v1/runs/${runId}/share`,
        request
      );
      return response.data;
    },
    onSuccess: () => {
      // Invalidate share tokens list
      void queryClient.invalidateQueries({ queryKey: ["shareTokens", runId] });
    },
  });
}

/**
 * Hook to list all share tokens for a run
 */
export function useShareTokens(runId: string) {
  return useQuery({
    queryKey: ["shareTokens", runId],
    queryFn: async () => {
      const response = await api.get<ShareToken[]>(`/api/v1/runs/${runId}/shares`);
      return response.data;
    },
  });
}

/**
 * Hook to revoke a share token
 */
export function useRevokeShareToken(runId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (tokenId: string) => {
      await api.delete(`/api/v1/runs/${runId}/shares/${tokenId}`);
    },
    onSuccess: () => {
      // Invalidate share tokens list
      void queryClient.invalidateQueries({ queryKey: ["shareTokens", runId] });
    },
  });
}
