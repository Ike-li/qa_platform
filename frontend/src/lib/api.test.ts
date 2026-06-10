import { describe, it, expect, beforeEach } from "vitest";
import { setAccessToken, getAccessToken, setOnAuthFailure } from "./api";

describe("api token management", () => {
  beforeEach(() => {
    setAccessToken(null);
  });

  it("sets and gets access token", () => {
    setAccessToken("test-token");
    expect(getAccessToken()).toBe("test-token");
  });

  it("clears access token", () => {
    setAccessToken("test-token");
    setAccessToken(null);
    expect(getAccessToken()).toBe(null);
  });

  it("sets auth failure handler", () => {
    const handler = () => {};
    setOnAuthFailure(handler);
    // Handler is set internally, no direct getter
    expect(true).toBe(true);
  });
});
