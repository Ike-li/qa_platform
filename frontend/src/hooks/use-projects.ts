import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import { unwrapPaginated } from "../lib/utils";
import type { Project, PaginatedResponse, Pipeline, Environment } from "../types/api";

type BackendEnvironment = Omit<Environment, "variables"> & {
  env_vars?: Record<string, string>;
  variables?: Record<string, string>;
};

function normalizeEnvironment(env: Environment | BackendEnvironment): Environment {
  const backendEnv = env as BackendEnvironment;
  return {
    ...env,
    variables: backendEnv.variables ?? backendEnv.env_vars ?? {},
  };
}

function toEnvironmentPayload(env: Partial<Environment>) {
  const { variables, env_vars, ...rest } = env;
  return {
    ...rest,
    ...(variables !== undefined || env_vars !== undefined
      ? { env_vars: variables ?? env_vars ?? {} }
      : {}),
  };
}

export function useProjects(params?: { page?: number; per_page?: number; search?: string; status?: string; enabled?: boolean }) {
  const { enabled, ...apiParams } = params ?? {};
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
    mutationFn: async (project: Partial<Project>) => {
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
    mutationFn: async (project: Partial<Project>) => {
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
      const { data } = await api.get<Pipeline[] | PaginatedResponse<Pipeline>>(`/projects/${projectId}/pipelines`);
      return unwrapPaginated(data);
    },
    enabled: !!projectId,
    staleTime: 60_000,
  });
}

export function useCreatePipeline(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pipeline: Partial<Pipeline>) => {
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
      const { data } = await api.get<Environment[] | PaginatedResponse<Environment>>(`/projects/${projectId}/environments`);
      return unwrapPaginated(data).map(normalizeEnvironment);
    },
    enabled: !!projectId,
    staleTime: 60_000,
  });
}

export function useCreateEnvironment(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (env: Partial<Environment>) => {
      const { data } = await api.post<Environment>(`/projects/${projectId}/environments`, toEnvironmentPayload(env));
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
    mutationFn: async (env: Partial<Environment>) => {
      const { data } = await api.put<Environment>(`/projects/${projectId}/environments/${envId}`, toEnvironmentPayload(env));
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
