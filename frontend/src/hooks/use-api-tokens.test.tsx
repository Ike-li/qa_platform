import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useApiTokens,
  useCreateApiToken,
} from "./use-api-tokens";
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

  it("fetches API tokens list successfully", async () => {
    const { result } = renderHook(() => useApiTokens(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.data).toHaveLength(2);
    expect(result.current.data?.data[0].name).toBe("CI Token");
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

  it("creates API token successfully", async () => {
    const { result } = renderHook(() => useCreateApiToken(), {
      wrapper: createWrapper(queryClient),
    });

    const payload = {
      name: "New Token",
      scopes: ["run.read", "project.read"],
    };

    result.current.mutate(payload);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.name).toBe("New Token");
    expect(result.current.data?.token).toBe("qap_test_token_1234567890");
  });

  it("invalidates tokens queries after creation", async () => {
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useCreateApiToken(), {
      wrapper: createWrapper(queryClient),
    });

    result.current.mutate({
      name: "Test Token",
      scopes: ["run.read"],
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["api-tokens"] });
  });
});
