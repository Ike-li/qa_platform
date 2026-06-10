import { describe, it, expect, vi, beforeEach } from "vitest";
import api, {
  setAccessToken,
  getAccessToken,
  setOnAuthFailure,
  refreshAccessToken,
  getArtifactDownloadUrl,
  getArtifactPreviewUrl,
} from "./api";
import { server } from "../test/setup";
import { http, HttpResponse } from "msw";

describe("api", () => {
  beforeEach(() => {
    setAccessToken(null);
    setOnAuthFailure(() => {});
  });

  it("sets and gets access token", () => {
    setAccessToken("test-token");
    expect(getAccessToken()).toBe("test-token");

    setAccessToken(null);
    expect(getAccessToken()).toBe(null);
  });

  it("sets auth failure handler", () => {
    const handler = vi.fn();
    setOnAuthFailure(handler);
    expect(handler).not.toHaveBeenCalled();
  });

  it("refreshes access token successfully", async () => {
    server.use(
      http.post("/api/v1/auth/refresh", () => {
        return HttpResponse.json({ access_token: "new-token" });
      })
    );

    const token = await refreshAccessToken();
    expect(token).toBe("new-token");
    expect(getAccessToken()).toBe("new-token");
  });

  it("handles refresh token failure", async () => {
    server.use(
      http.post("/api/v1/auth/refresh", () => {
        return new HttpResponse(null, { status: 401 });
      })
    );

    await expect(refreshAccessToken()).rejects.toThrow();
    expect(getAccessToken()).toBe(null);
  });

  it("gets artifact download url", async () => {
    server.use(
      http.get("/api/v1/artifacts/:id/download", () => {
        return HttpResponse.json({ download_url: "https://example.com/download" });
      })
    );

    const url = await getArtifactDownloadUrl("art-1");
    expect(url).toBe("https://example.com/download");
  });

  it("gets artifact preview url", async () => {
    server.use(
      http.get("/api/v1/artifacts/:id/preview-url", () => {
        return HttpResponse.json({ preview_url: "https://example.com/preview" });
      })
    );

    const url = await getArtifactPreviewUrl("art-1");
    expect(url).toBe("https://example.com/preview");
  });

  it("adds authorization header when token is set", async () => {
    setAccessToken("test-token");

    server.use(
      http.get("/api/v1/test", ({ request }) => {
        const auth = request.headers.get("authorization");
        return HttpResponse.json({ auth });
      })
    );

    const response = await api.get("/test");
    expect(response.data.auth).toBe("Bearer test-token");
  });

  it("retries request on 401 with refresh", async () => {
    setAccessToken("old-token");
    let callCount = 0;

    server.use(
      http.get("/api/v1/test", () => {
        callCount++;
        if (callCount === 1) {
          return new HttpResponse(null, { status: 401 });
        }
        return HttpResponse.json({ success: true });
      }),
      http.post("/api/v1/auth/refresh", () => {
        return HttpResponse.json({ access_token: "new-token" });
      })
    );

    const response = await api.get("/test");
    expect(response.data.success).toBe(true);
    expect(getAccessToken()).toBe("new-token");
  });

  it("calls onAuthFailure when refresh fails on 401", async () => {
    const onAuthFailure = vi.fn();
    setOnAuthFailure(onAuthFailure);
    setAccessToken("old-token");

    server.use(
      http.get("/api/v1/test", () => {
        return new HttpResponse(null, { status: 401 });
      }),
      http.post("/api/v1/auth/refresh", () => {
        return new HttpResponse(null, { status: 401 });
      })
    );

    await expect(api.get("/test")).rejects.toThrow();
    expect(onAuthFailure).toHaveBeenCalled();
    expect(getAccessToken()).toBe(null);
  });
});
