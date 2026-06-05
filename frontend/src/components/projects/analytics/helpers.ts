import type { FlakyTest, TestHistoryPoint } from "../../../types/api";

export const PERIOD_OPTIONS = [7, 14, 30, 90];

export function testKey(test: Pick<FlakyTest, "suite" | "name">) {
  return `${test.suite}\u0000${test.name}`;
}

export function formatDateTime(value: string) {
  return new Date(value).toLocaleString();
}

export function historyStatusClass(status: TestHistoryPoint["status"]) {
  if (status === "passed") return "text-status-passed";
  if (status === "failed" || status === "error") return "text-status-failed";
  if (status === "skipped" || status === "xfail") return "text-status-skipped";
  return "text-ink-muted";
}

export function formatPercent(value: number | null) {
  if (value === null) return "-";
  return `${Math.round(value * 100)}%`;
}
