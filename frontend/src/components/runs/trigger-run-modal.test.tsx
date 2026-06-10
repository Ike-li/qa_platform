import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "../../test/test-utils";
import { TriggerRunModal } from "./trigger-run-modal";
import { QueryClient } from "@tanstack/react-query";

describe("TriggerRunModal", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("renders modal when open", () => {
    render(
      <TriggerRunModal
        projectId="proj-1"
        open={true}
        onOpenChange={vi.fn()}
      />,
      { queryClient, withRouter: true }
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("loads pipelines on mount", async () => {
    render(
      <TriggerRunModal
        projectId="proj-1"
        open={true}
        onOpenChange={vi.fn()}
      />,
      { queryClient, withRouter: true }
    );

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /trigger/i });
      expect(button).toBeInTheDocument();
    });
  });

  it("accepts default pipeline id", () => {
    render(
      <TriggerRunModal
        projectId="proj-1"
        open={true}
        onOpenChange={vi.fn()}
        defaultPipelineId="pipe-1"
      />,
      { queryClient, withRouter: true }
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
