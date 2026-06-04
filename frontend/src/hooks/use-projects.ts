import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type {
  Project,
  GitBranchDiscoveryResponse,
  PaginatedResponse,
  Pipeline,
  Environment,
  EnvironmentResponse,
  CreateEnvironmentPayload,
  PipelineCreatePayload,
  ProjectCreatePayload,
  ProjectUpdatePayload,
  UpdateEnvironmentPayload
} from "../types/api";

function normalizeEnvironment(env: EnvironmentResponse): Environment {
  const { env_vars, ...rest } = env;
  return {
    ...rest,
    variables: env_vars ?? {},
  };
}

export function useProjects(params?: { page?: number; per_page?: number; search?: string; status?: string; enabled?: boolean }) {
  const { enabled, search, ...restParams } = params ?? {};
  const apiParams = { ...restParams, ...(search ? { q: search } : {}) };
  return useQuery({
    queryKey: ["projects", apiParams],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Project>>("/projects", { params: apiParams });
      return data;
    },
    enabled,
    staleTime: 30_000,
  });
}

export async function discoverGitBranches(payload: {
  git_url: string;
  git_auth_method?: ProjectCreatePayload["git_auth_method"];
}): Promise<GitBranchDiscoveryResponse> {
  const { data } = await api.post<GitBranchDiscoveryResponse>("/projects/branches", payload);
  return data;
}

export function useProject(id: string) {
  return useQuery({
    queryKey: ["projects", id],
    queryFn: async () => {
      const { data } = await api.get<Project>(`/projects/${id}`);
      return data;
    },
    enabled: !!id,
    staleTime: 60_000,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (project: ProjectCreatePayload) => {
      const { data } = await api.post<Project>("/projects", project);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useUpdateProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (project: ProjectUpdatePayload) => {
      const { data } = await api.put<Project>(`/projects/${id}`, project);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["projects", id] });
    },
  });
}

export function useDeleteProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.delete(`/projects/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useProjectPipelines(projectId: string) {
  return useQuery({
    queryKey: ["projects", projectId, "pipelines"],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Pipeline>>(`/projects/${projectId}/pipelines`);
      return data.data;
    },
    enabled: !!projectId,
    staleTime: 60_000,
  });
}

export function useCreatePipeline(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pipeline: PipelineCreatePayload) => {
      const { data } = await api.post<Pipeline>(`/projects/${projectId}/pipelines`, pipeline);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "pipelines"] });
    },
  });
}

export function useProjectEnvironments(projectId: string) {
  return useQuery({
    queryKey: ["projects", projectId, "environments"],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<EnvironmentResponse>>(`/projects/${projectId}/environments`);
      return data.data.map(normalizeEnvironment);
    },
    enabled: !!projectId,
    staleTime: 60_000,
  });
}

export function useCreateEnvironment(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (env: CreateEnvironmentPayload) => {
      const { data } = await api.post<EnvironmentResponse>(`/projects/${projectId}/environments`, env);
      return normalizeEnvironment(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "environments"] });
    },
  });
}

export function useUpdateEnvironment(projectId: string, envId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (env: UpdateEnvironmentPayload) => {
      const { data } = await api.put<EnvironmentResponse>(`/projects/${projectId}/environments/${envId}`, env);
      return normalizeEnvironment(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "environments"] });
    },
  });
}

export function useDeleteEnvironment(projectId: string, envId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.delete(`/projects/${projectId}/environments/${envId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "environments"] });
    },
  });
}
