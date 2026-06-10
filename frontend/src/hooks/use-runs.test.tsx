import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRuns, useRun } from "./use-runs";
import { server } from "../test/setup";
import { http, HttpResponse } from "msw";
import { createMockRun } from "../test/mocks/fixtures";
import type { ReactNode } from "react";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("useRuns", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("fetches runs list successfully", async () => {
    const { result } = renderHook(() => useRuns(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.data).toHaveLength(2);
    expect(result.current.data?.data[0].status).toBeDefined();
  });

  it("passes search parameters correctly", async () => {
    let capturedUrl = "";
    server.use(
      http.get("/api/v1/runs", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({
          data: [],
          total: 0,
          page: 1,
          per_page: 20,
        });
      })
    );

    const { result } = renderHook(
      () => useRuns({ page: 2, per_page: 10, project_id: "proj-1" }),
      {
        wrapper: createWrapper(queryClient),
      }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl);
    expect(url.searchParams.get("page")).toBe("2");
    expect(url.searchParams.get("per_page")).toBe("10");
    expect(url.searchParams.get("project_id")).toBe("proj-1");
  });

  it("handles API error", async () => {
    server.use(
      http.get("/api/v1/runs", () => {
        return new HttpResponse(null, { status: 500 });
      })
    );

    const { result } = renderHook(() => useRuns(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeDefined();
  });
});

describe("useRun", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("fetches single run successfully", async () => {
    const { result } = renderHook(() => useRun("run-success"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.id).toBe("run-success");
    expect(result.current.data?.status).toBe("passed");
  });

  it("normalizes done status with failed tests to failed", async () => {
    server.use(
      http.get("/api/v1/runs/:id", () => {
        return HttpResponse.json(
          createMockRun({
            id: "run-1",
            status: "done",
            summary: { total: 10, passed: 8, failed: 2, skipped: 0, error: 0 },
          })
        );
      })
    );

    const { result } = renderHook(() => useRun("run-1"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.status).toBe("failed");
    expect(result.current.data?.failed_tests).toBe(2);
  });

  it("normalizes done status with all passed tests to passed", async () => {
    server.use(
      http.get("/api/v1/runs/:id", () => {
        return HttpResponse.json(
          createMockRun({
            id: "run-2",
            status: "done",
            summary: { total: 10, passed: 10, failed: 0, skipped: 0, error: 0 },
          })
        );
      })
    );

    const { result } = renderHook(() => useRun("run-2"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.status).toBe("passed");
  });

  it("normalizes timeout status to timed_out", async () => {
    server.use(
      http.get("/api/v1/runs/:id", () => {
        return HttpResponse.json(
          createMockRun({
            id: "run-3",
            status: "timeout",
          })
        );
      })
    );

    const { result } = renderHook(() => useRun("run-3"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.status).toBe("timed_out");
  });

  it("marks terminal statuses correctly", async () => {
    server.use(
      http.get("/api/v1/runs/:id", () => {
        return HttpResponse.json(
          createMockRun({
            id: "run-4",
            status: "done",
            summary: { total: 5, passed: 5, failed: 0 },
          })
        );
      })
    );

    const { result } = renderHook(() => useRun("run-4"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.is_terminal).toBe(true);
  });

  it("returns 404 for non-existent run", async () => {
    server.use(
      http.get("/api/v1/runs/:id", () => {
        return new HttpResponse(null, { status: 404 });
      })
    );

    const { result } = renderHook(() => useRun("run-nonexistent"), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
