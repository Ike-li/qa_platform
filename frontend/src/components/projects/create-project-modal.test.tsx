import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "../../test/test-utils";
import { CreateProjectModal } from "./create-project-modal";
import { QueryClient } from "@tanstack/react-query";
import { server } from "../../test/setup";
import { http, HttpResponse } from "msw";

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

  it("shows required fields", () => {
    render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/slug/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/github.com/i)).toBeInTheDocument();
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

  it("creates project successfully", async () => {
    const onOpenChange = vi.fn();

    server.use(
      http.post("/api/v1/projects", async () => {
        return HttpResponse.json(
          {
            id: "proj-new",
            name: "Test Project",
            slug: "test-project",
            git_url: "https://github.com/test/repo",
          },
          { status: 201 }
        );
      })
    );

    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={onOpenChange} />,
      { queryClient, withRouter: true }
    );

    await user.type(screen.getByLabelText(/name/i), "Test Project");

    const gitUrlInput = screen.getByPlaceholderText(/github.com/i);
    await user.type(gitUrlInput, "https://github.com/test/repo");

    const submitButton = screen.getByRole("button", { name: /create/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("shows error on create failure", async () => {
    server.use(
      http.post("/api/v1/projects", async () => {
        return HttpResponse.json(
          { detail: "Project already exists" },
          { status: 400 }
        );
      })
    );

    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    await user.type(screen.getByLabelText(/name/i), "Test Project");

    const gitUrlInput = screen.getByPlaceholderText(/github.com/i);
    await user.type(gitUrlInput, "https://github.com/test/repo");

    const submitButton = screen.getByRole("button", { name: /create/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
  });

  it("discovers branches for public repo", async () => {
    server.use(
      http.post("/api/v1/projects/branches", async () => {
        return HttpResponse.json({
          branches: ["main", "develop", "feature/test"],
          default_branch: "main",
        });
      })
    );

    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const gitUrlInput = screen.getByPlaceholderText(/github.com/i);
    await user.type(gitUrlInput, "https://github.com/test/repo.git");

    await waitFor(() => {
      expect(screen.getByText(/branches loaded/i)).toBeInTheDocument();
    });
  });

  it("shows error when branch discovery fails", async () => {
    server.use(
      http.post("/api/v1/projects/branches", async () => {
        return HttpResponse.json(
          { detail: "Failed to fetch branches" },
          { status: 400 }
        );
      })
    );

    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const gitUrlInput = screen.getByPlaceholderText(/github.com/i);
    await user.type(gitUrlInput, "https://github.com/test/repo.git");

    await waitFor(() => {
      expect(screen.getByText(/failed to fetch branches/i)).toBeInTheDocument();
    });
  });

  it("shows message for no branches found", async () => {
    server.use(
      http.post("/api/v1/projects/branches", async () => {
        return HttpResponse.json({
          branches: [],
          default_branch: null,
        });
      })
    );

    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const gitUrlInput = screen.getByPlaceholderText(/github.com/i);
    await user.type(gitUrlInput, "https://github.com/test/repo.git");

    await waitFor(() => {
      expect(screen.getByText(/no branches found/i)).toBeInTheDocument();
    });
  });

  it("disables branch discovery for authenticated repos", async () => {
    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const gitUrlInput = screen.getByPlaceholderText(/github.com/i);
    await user.type(gitUrlInput, "https://github.com/test/repo.git");

    // Branches should be loaded for public repo (after 500ms debounce)
    await waitFor(
      () => {
        expect(screen.getByText(/branches loaded/i)).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
  });

  it("auto-selects discovered default branch", async () => {
    server.use(
      http.post("/api/v1/projects/branches", async () => {
        return HttpResponse.json({
          branches: ["main", "develop", "feature/test"],
          default_branch: "develop",
        });
      })
    );

    const { user } = render(
      <CreateProjectModal open={true} onOpenChange={vi.fn()} />,
      { queryClient, withRouter: true }
    );

    const gitUrlInput = screen.getByPlaceholderText(/github.com/i);
    await user.type(gitUrlInput, "https://github.com/test/repo.git");

    await waitFor(() => {
      expect(screen.getByText(/3 branches loaded/i)).toBeInTheDocument();
    });
  });
});
