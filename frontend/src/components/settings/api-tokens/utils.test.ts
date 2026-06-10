import { describe, it, expect } from "vitest";
import { parseScopes, formatDate, errorDetail, scopeLabel, tokenStatusLabel } from "./utils";

describe("parseScopes", () => {
  it("parses comma-separated scopes", () => {
    expect(parseScopes("read, write, admin")).toEqual(["read", "write", "admin"]);
  });

  it("trims whitespace", () => {
    expect(parseScopes("  read  ,  write  ")).toEqual(["read", "write"]);
  });

  it("returns default wildcard for empty string", () => {
    expect(parseScopes("")).toEqual(["*"]);
  });

  it("returns default wildcard for whitespace only", () => {
    expect(parseScopes("   ")).toEqual(["*"]);
  });
});

describe("formatDate", () => {
  it("formats valid date", () => {
    const result = formatDate("2024-01-01T12:00:00Z", "en-US");
    expect(result).toContain("2024");
  });

  it("returns dash for null", () => {
    expect(formatDate(null, "en-US")).toBe("-");
  });

  it("returns dash for invalid date", () => {
    expect(formatDate("invalid", "en-US")).toBe("-");
  });
});

describe("errorDetail", () => {
  it("extracts detail from axios error", () => {
    const error = {
      response: { data: { detail: "Invalid token" } },
    };
    expect(errorDetail(error, "Fallback")).toBe("Invalid token");
  });

  it("returns fallback for unknown error", () => {
    expect(errorDetail({}, "Fallback")).toBe("Fallback");
  });
});

describe("scopeLabel", () => {
  it("joins scopes with comma", () => {
    expect(scopeLabel(["read", "write"])).toBe("read, write");
  });

  it("returns wildcard for empty array", () => {
    expect(scopeLabel([])).toBe("*");
  });
});

describe("tokenStatusLabel", () => {
  const t = (key: string) => key;

  it("returns revoked status", () => {
    expect(tokenStatusLabel(true, t)).toBe("settings.tokens.status.revoked");
  });

  it("returns active status", () => {
    expect(tokenStatusLabel(false, t)).toBe("settings.tokens.status.active");
  });
});
