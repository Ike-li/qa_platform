import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import type { TrendDataPoint, FlakyTest } from "../types/api";

interface PaginatedAnalytics<T> {
  data: T[];
  pagination: { offset: number; limit: number; total: number };
}

export function useTrends(projectId: string, days: number = 30) {
  return useQuery({
    queryKey: ["projects", projectId, "trends", days],
    queryFn: async () => {
      const { data } = await api.get<PaginatedAnalytics<TrendDataPoint>>(
        `/projects/${projectId}/analytics/trends`,
        { params: { days } },
      );
      return data.data;
    },
    enabled: !!projectId,
  });
}

export function useFlakyTests(projectId: string, days: number = 30, minRuns: number = 3) {
  return useQuery({
    queryKey: ["projects", projectId, "flaky", days, minRuns],
    queryFn: async () => {
      const { data } = await api.get<PaginatedAnalytics<FlakyTest>>(
        `/projects/${projectId}/analytics/flaky`,
        { params: { days, min_runs: minRuns } },
      );
      return data.data;
    },
    enabled: !!projectId,
  });
}
