import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "../../test/test-utils";
import { RetryFailedButton } from "./retry-failed-button";
import { server } from "../../test/setup";
import { http, HttpResponse } from "msw";

const RUN_ID = "11111111-1111-1111-1111-111111111111";
const NEW_RUN_ID = "22222222-2222-2222-2222-222222222222";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

function mockRetryFailed(newRunId = NEW_RUN_ID) {
  server.use(
    http.post(`*/runs/${RUN_ID}/retry-failed`, () =>
      HttpResponse.json({
        id: newRunId,
        tenant_id: "t",
        project_id: "p",
        pipeline_id: "pl",
        pipeline_name: "ci",
        environment_id: "env",
        status: "queued",
        trigger_type: "retry_failed",
        priority: 1,
        triggered_by: "u",
        git_ref: "main",
        git_sha: null,
        attempt: 2,
        started_at: null,
        finished_at: null,
        duration_ms: null,
        summary: null,
        error_message: null,
        created_at: "2026-06-16T00:00:00Z",
        updated_at: "2026-06-16T00:00:00Z",
      })
    )
  );
}

describe("RetryFailedButton", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
  });

  it("无失败用例时不渲染（failedCount=0）", () => {
    render(<RetryFailedButton runId={RUN_ID} failedCount={0} />);
    expect(screen.queryByTestId("retry-failed-button")).toBeNull();
  });

  it("有失败用例时渲染按钮", () => {
    render(<RetryFailedButton runId={RUN_ID} failedCount={3} />);
    expect(screen.queryByTestId("retry-failed-button")).not.toBeNull();
  });

  it("点击后调用 retry-failed 接口并跳转到新 run", async () => {
    mockRetryFailed();
    const { user } = render(<RetryFailedButton runId={RUN_ID} failedCount={3} />);
    await user.click(screen.getByTestId("retry-failed-button"));
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(`/runs/${NEW_RUN_ID}`);
    });
  });
});
