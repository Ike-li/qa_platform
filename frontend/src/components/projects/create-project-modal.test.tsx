import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "../../test/test-utils";
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

  it("validates slug format", async () => {
    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const slugInput = screen.getByLabelText(/slug/i);
    const nameInput = screen.getByLabelText(/name/i);
    
    await user.type(nameInput, "Test");
    await user.clear(slugInput);
    await user.type(slugInput, "Invalid_Slug!");

    const submitButton = screen.getByRole("button", { name: /create/i });
    await user.click(submitButton);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("auto-generates slug from name", async () => {
    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const nameInput = screen.getByLabelText(/name/i);
    await user.type(nameInput, "My New Project");

    await waitFor(() => {
      const slugInput = screen.getByLabelText(/slug/i);
      expect(slugInput).toHaveValue("my-new-project");
    });
  });
});
