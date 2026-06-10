import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useApiTokens, useCreateApiToken, useRevokeApiToken } from "./use-api-tokens";
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

describe("useApiTokens", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("fetches api tokens successfully", async () => {
    const { result } = renderHook(() => useApiTokens(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
      expect(result.current.data).toBeDefined();
    });
  });

  it("supports pagination parameters", async () => {
    let capturedUrl = "";
    server.use(
      http.get("/api/v1/auth/tokens", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({
          data: [],
          total: 0,
          page: 2,
          per_page: 10,
        });
      })
    );

    const { result } = renderHook(() => useApiTokens({ page: 2, per_page: 10 }), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl);
    expect(url.searchParams.get("page")).toBe("2");
    expect(url.searchParams.get("per_page")).toBe("10");
  });

  it("uses default pagination", async () => {
    let capturedUrl = "";
    server.use(
      http.get("/api/v1/auth/tokens", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({
          data: [],
          total: 0,
          page: 1,
          per_page: 20,
        });
      })
    );

    const { result } = renderHook(() => useApiTokens({}), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl);
    expect(url.searchParams.get("page")).toBe("1");
    expect(url.searchParams.get("per_page")).toBe("20");
  });
});

describe("useCreateApiToken", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("creates api token successfully", async () => {
    const { result } = renderHook(() => useCreateApiToken(), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate({
      name: "Test Token",
      scopes: ["*"],
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.name).toBe("Test Token");
  });

  it("invalidates queries on success", async () => {
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useCreateApiToken(), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate({ name: "Test", scopes: ["*"] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["api-tokens"] });
  });
});

describe("useRevokeApiToken", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("revokes api token successfully", async () => {
    server.use(
      http.delete("/api/v1/auth/tokens/:id", async () => {
        return new HttpResponse(null, { status: 204 });
      })
    );

    const { result } = renderHook(() => useRevokeApiToken(), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate("token-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("invalidates queries after revocation", async () => {
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useRevokeApiToken(), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate("token-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["api-tokens"] });
  });
});
