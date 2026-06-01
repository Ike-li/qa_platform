import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type {
  ApiTokenListItem,
  ApiTokenResponse,
  CreateApiTokenPayload,
  PaginatedResponse,
} from "../types/api";

export function useApiTokens(params: { page?: number; per_page?: number } = {}) {
  const apiParams = { page: params.page ?? 1, per_page: params.per_page ?? 20 };

  return useQuery({
    queryKey: ["api-tokens", apiParams],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<ApiTokenListItem>>(
        "/auth/tokens",
        { params: apiParams },
      );
      return data;
    },
    staleTime: 30_000,
  });
}

export function useCreateApiToken() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateApiTokenPayload) => {
      const { data } = await api.post<ApiTokenResponse>("/auth/tokens", payload);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-tokens"] });
    },
  });
}

export function useRevokeApiToken() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (tokenId: string) => {
      await api.delete(`/auth/tokens/${tokenId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-tokens"] });
    },
  });
}
