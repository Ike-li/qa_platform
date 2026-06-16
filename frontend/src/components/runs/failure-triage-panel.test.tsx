import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "../../test/test-utils";
import { FailureTriagePanel } from "./failure-triage-panel";
import { QueryClient } from "@tanstack/react-query";
import { server } from "../../test/setup";
import { http, HttpResponse } from "msw";
import type { RunTriageResponse, TriageItem } from "../../types/api";

const RUN_ID = "11111111-1111-1111-1111-111111111111";

function makeItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    suite: "tests.unit.test_x",
    name: "test_a",
    status: "failed",
    duration_ms: 10,
    error_message: "AssertionError: expected <num> got <num>",
    stack_trace: "Traceback ...",
    category: "new",
    confidence: "established",
    observation_count: 12,
    quarantined: false,
    recent_history: [
      {
        run_id: RUN_ID,
        run_created_at: "2026-06-10T12:00:00Z",
        status: "failed",
      },
    ],
    ...overrides,
  };
}

function mockTriage(body: RunTriageResponse) {
  server.use(
    http.get(`*/runs/${RUN_ID}/triage`, () => HttpResponse.json(body))
  );
}

describe("FailureTriagePanel", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("renders the three triage groups with counts", async () => {
    mockTriage({
      run_id: RUN_ID,
      total_failed: 4,
      new: [
        {
          signature: "AssertionError: expected <num> got <num>",
          count: 2,
          items: [
            makeItem({ name: "test_a", category: "new" }),
            makeItem({ name: "test_b", category: "new" }),
          ],
        },
      ],
      known_flaky: [
        {
          signature: "TimeoutError: flaky",
          count: 1,
          items: [makeItem({ name: "test_flip", category: "known_flaky" })],
        },
      ],
      persistent: [
        {
          signature: "RuntimeError: stuck",
          count: 1,
          items: [makeItem({ name: "test_stuck", category: "persistent" })],
        },
      ],
    });

    render(<FailureTriagePanel runId={RUN_ID} />, { queryClient });

    await waitFor(() => {
      expect(screen.getByText("New failures")).toBeInTheDocument();
    });
    expect(screen.getByText("Known flaky")).toBeInTheDocument();
    expect(screen.getByText("Persistent failures")).toBeInTheDocument();

    // 新增失败组默认展开：组内用例与签名可见。
    expect(screen.getByText("test_a")).toBeInTheDocument();
    expect(screen.getByText("test_b")).toBeInTheDocument();
    expect(
      screen.getByText("AssertionError: expected <num> got <num>")
    ).toBeInTheDocument();
    // 其他两组默认折叠：组内用例不可见。
    expect(screen.queryByText("test_flip")).not.toBeInTheDocument();
    expect(screen.queryByText("test_stuck")).not.toBeInTheDocument();
  });

  it("renders nothing when the run has no failures", async () => {
    mockTriage({
      run_id: RUN_ID,
      total_failed: 0,
      new: [],
      known_flaky: [],
      persistent: [],
    });

    const { container } = render(<FailureTriagePanel runId={RUN_ID} />, {
      queryClient,
    });

    await waitFor(() => {
      expect(screen.queryByTestId("triage-loading")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Failure Triage")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the observing badge for low-observation cases", async () => {
    mockTriage({
      run_id: RUN_ID,
      total_failed: 1,
      new: [
        {
          signature: "RuntimeError: first",
          count: 1,
          items: [
            makeItem({
              name: "test_fresh",
              confidence: "observing",
              observation_count: 1,
            }),
          ],
        },
      ],
      known_flaky: [],
      persistent: [],
    });

    render(<FailureTriagePanel runId={RUN_ID} />, { queryClient });

    await waitFor(() => {
      expect(screen.getByText("Observing (1 runs)")).toBeInTheDocument();
    });
  });

  it("does not show the observing badge for established cases", async () => {
    mockTriage({
      run_id: RUN_ID,
      total_failed: 1,
      new: [
        {
          signature: "RuntimeError: seasoned",
          count: 1,
          items: [makeItem({ confidence: "established" })],
        },
      ],
      known_flaky: [],
      persistent: [],
    });

    render(<FailureTriagePanel runId={RUN_ID} />, { queryClient });

    await waitFor(() => {
      expect(screen.getByText("test_a")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Observing/)).not.toBeInTheDocument();
  });
});
