import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "../../../test/test-utils";
import { CreateApiTokenDialog } from "./create-api-token-dialog";
import { QueryClient } from "@tanstack/react-query";
import { server } from "../../../test/setup";
import { http, HttpResponse } from "msw";

describe("CreateApiTokenDialog", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  it("renders dialog when open", () => {
    render(
      <CreateApiTokenDialog
        open={true}
        onOpenChange={vi.fn()}
        onCreated={vi.fn()}
      />,
      { queryClient }
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("has required fields", () => {
    render(
      <CreateApiTokenDialog
        open={true}
        onOpenChange={vi.fn()}
        onCreated={vi.fn()}
      />,
      { queryClient }
    );

    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/scopes/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/expires/i)).toBeInTheDocument();
  });

  it("has default scopes value", () => {
    render(
      <CreateApiTokenDialog
        open={true}
        onOpenChange={vi.fn()}
        onCreated={vi.fn()}
      />,
      { queryClient }
    );

    const scopesInput = screen.getByLabelText(/scopes/i);
    expect(scopesInput).toHaveValue("*");
  });

  it("creates token successfully", async () => {
    const onCreated = vi.fn();
    const onOpenChange = vi.fn();

    server.use(
      http.post("/api/v1/auth/tokens", async () => {
        return HttpResponse.json(
          {
            id: "token-new",
            name: "Test Token",
            scopes: ["*"],
            token: "qap_test_xyz",
            created_at: "2024-01-01T00:00:00Z",
          },
          { status: 201 }
        );
      })
    );

    const { user } = render(
      <CreateApiTokenDialog
        open={true}
        onOpenChange={onOpenChange}
        onCreated={onCreated}
      />,
      { queryClient }
    );

    const nameInput = screen.getByLabelText(/name/i);
    await user.type(nameInput, "Test Token");

    const submitButton = screen.getByRole("button", { name: /create/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalled();
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
