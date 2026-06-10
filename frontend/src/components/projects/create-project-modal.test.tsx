import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "../../test/test-utils";
import { CreateProjectModal } from "./create-project-modal";
import { QueryClient } from "@tanstack/react-query";
import { vi } from "vitest";

describe("CreateProjectModal", () => {
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
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("has default values", () => {
    render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const branchInput = screen.getByDisplayValue("main");
    expect(branchInput).toBeInTheDocument();

    const rootPathInput = screen.getByDisplayValue("/");
    expect(rootPathInput).toBeInTheDocument();
  });

  it("has create button", () => {
    render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    expect(screen.getByRole("button", { name: /create/i })).toBeInTheDocument();
  });
});
