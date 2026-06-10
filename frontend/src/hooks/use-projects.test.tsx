import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useProjects,
  useProject,
  useCreateProject,
  useDeleteProject,
} from "./use-projects";
import { server } from "../test/setup";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("useProjects", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("fetches projects list successfully", async () => {
    const { result } = renderHook(() => useProjects(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.data).toHaveLength(3);
    expect(result.current.data?.data[0].name).toBe("Project Alpha");
  });

  it("handles pagination parameters", async () => {
    let capturedUrl = "";
    server.use(
      http.get("/api/v1/projects", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({
          data: [],
          total: 0,
          page: 2,
          per_page: 10,
        });
      })
    );

    const { result } = renderHook(() => useProjects({ page: 2, per_page: 10 }), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl);
    expect(url.searchParams.get("page")).toBe("2");
    expect(url.searchParams.get("per_page")).toBe("10");
  });
});

describe("useProject", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("fetches single project successfully", async () => {
    const { result } = renderHook(() => useProject("proj-1"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.id).toBe("proj-1");
  });

  it("returns 404 for non-existent project", async () => {
    server.use(
      http.get("/api/v1/projects/:id", () => {
        return new HttpResponse(null, { status: 404 });
      })
    );

    const { result } = renderHook(() => useProject("proj-nonexistent"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCreateProject", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("creates project successfully", async () => {
    const { result } = renderHook(() => useCreateProject(), {
      wrapper: createWrapper(queryClient),
    });

    const payload = {
      name: "New Project",
      slug: "new-project",
      git_url: "https://github.com/test/new-repo",
      git_auth_method: "none" as const,
      default_branch: "main",
    };

    result.current.mutate(payload);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.name).toBe("New Project");
  });

  it("invalidates projects queries after creation", async () => {
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useCreateProject(), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate({
      name: "Test",
      slug: "test",
      git_url: "https://github.com/test/repo",
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["projects"] });
  });
});

describe("useDeleteProject", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("deletes project successfully", async () => {
    const { result } = renderHook(() => useDeleteProject("proj-1"), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("invalidates queries after deletion", async () => {
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useDeleteProject("proj-1"), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["projects"] });
  });
});
