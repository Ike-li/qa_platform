import { useSyncExternalStore } from "react";

function formatRelativeTime(date: Date) {
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diffInSeconds < 60) return "just now";
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  if (diffInSeconds < 604800) return `${Math.floor(diffInSeconds / 86400)}d ago`;

  return date.toLocaleDateString();
}

let tick = 0;
let listeners: Set<() => void> = new Set();
let intervalId: ReturnType<typeof setInterval> | null = null;

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!intervalId) {
    intervalId = setInterval(() => {
      tick++;
      listeners.forEach((l) => l());
    }, 60000);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
  };
}

function getSnapshot() {
  return tick;
}

export function RelativeTime({ date }: { date: string | Date }) {
  const d = typeof date === "string" ? new Date(date) : date;
  useSyncExternalStore(subscribe, getSnapshot);

  return (
    <time dateTime={d.toISOString()} title={d.toLocaleString()} className="cursor-help">
      {formatRelativeTime(d)}
    </time>
  );
}
