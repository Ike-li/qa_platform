import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import type { TrendDataPoint, FlakyTest, TestHistoryPoint, ReleaseSummary } from "../types/api";

interface PaginatedAnalytics<T> {
  data: T[];
  pagination: { offset: number; limit: number; total: number };
}

export function useTrends(projectId: string, days: number = 30, gitRef?: string) {
  const trimmedGitRef = gitRef?.trim() || undefined;
  return useQuery({
    queryKey: ["projects", projectId, "trends", days, trimmedGitRef],
    queryFn: async () => {
      const { data } = await api.get<PaginatedAnalytics<TrendDataPoint>>(
        `/projects/${projectId}/analytics/trends`,
        { params: { days, git_ref: trimmedGitRef } },
      );
      return data.data;
    },
    enabled: !!projectId,
  });
}

export function useFlakyTests(projectId: string, days: number = 30, minRuns: number = 3, gitRef?: string) {
  const trimmedGitRef = gitRef?.trim() || undefined;
  return useQuery({
    queryKey: ["projects", projectId, "flaky", days, minRuns, trimmedGitRef],
    queryFn: async () => {
      const { data } = await api.get<PaginatedAnalytics<FlakyTest>>(
        `/projects/${projectId}/analytics/flaky`,
        { params: { days, min_runs: minRuns, git_ref: trimmedGitRef } },
      );
      return data.data;
    },
    enabled: !!projectId,
  });
}

export function useReleaseSummary(
  projectId: string,
  days: number = 30,
  gitRef?: string,
  baselineGitRef?: string,
) {
  const trimmedGitRef = gitRef?.trim() || undefined;
  const trimmedBaselineGitRef = baselineGitRef?.trim() || undefined;
  return useQuery({
    queryKey: [
      "projects",
      projectId,
      "release-summary",
      days,
      trimmedGitRef,
      trimmedBaselineGitRef,
    ],
    queryFn: async () => {
      const { data } = await api.get<ReleaseSummary>(
        `/projects/${projectId}/analytics/release-summary`,
        {
          params: {
            days,
            git_ref: trimmedGitRef,
            baseline_git_ref: trimmedBaselineGitRef,
          },
        },
      );
      return data;
    },
    enabled: !!projectId,
  });
}

export function useTestHistory(
  projectId: string,
  suite: string | undefined,
  name: string | undefined,
  days: number = 30,
) {
  return useQuery({
    queryKey: ["projects", projectId, "test-history", suite, name, days],
    queryFn: async () => {
      const { data } = await api.get<PaginatedAnalytics<TestHistoryPoint>>(
        `/projects/${projectId}/analytics/test-history`,
        { params: { suite, name, days } },
      );
      return data.data;
    },
    enabled: !!projectId && !!suite && !!name,
  });
}
