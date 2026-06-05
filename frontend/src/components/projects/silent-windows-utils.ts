import type { SilentWindow } from "../../types/api";

export type SilentWindowFormValue = {
  start_at: string;
  end_at: string;
  reason: string;
};

function toDateTimeLocalValue(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function normalizeSilentWindows(windows: SilentWindowFormValue[]) {
  return windows.map((window) => {
    const start = new Date(window.start_at);
    const end = new Date(window.end_at);
    const reason = window.reason.trim();
    if (!window.start_at || !window.end_at || !reason) {
      throw new Error("required");
    }
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) {
      throw new Error("range");
    }
    return {
      start_at: start.toISOString(),
      end_at: end.toISOString(),
      reason,
    };
  });
}

export function toSilentWindowFormValues(windows: SilentWindow[] | undefined): SilentWindowFormValue[] {
  return (windows ?? []).map((window) => ({
    start_at: toDateTimeLocalValue(window.start_at),
    end_at: toDateTimeLocalValue(window.end_at),
    reason: window.reason,
  }));
}
