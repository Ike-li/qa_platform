import { useSyncExternalStore } from "react";
import i18n from "../i18n";

function formatRelativeTime(date: Date) {
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  const t = i18n.t.bind(i18n);

  if (diffInSeconds < 60) return t("time.justNow");
  if (diffInSeconds < 3600) return t("time.minutesAgo", { count: Math.floor(diffInSeconds / 60) });
  if (diffInSeconds < 86400) return t("time.hoursAgo", { count: Math.floor(diffInSeconds / 3600) });
  if (diffInSeconds < 604800) return t("time.daysAgo", { count: Math.floor(diffInSeconds / 86400) });

  return date.toLocaleDateString(i18n.language);
}

let tick = 0;
const listeners: Set<() => void> = new Set();
let intervalId: ReturnType<typeof setInterval> | null = null;

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onLangChange = () => { tick++; listeners.forEach((l) => l()); };
  i18n.on('languageChanged', onLangChange);
  if (!intervalId) {
    intervalId = setInterval(() => {
      tick++;
      listeners.forEach((l) => l());
    }, 60000);
  }
  return () => {
    listeners.delete(listener);
    i18n.off('languageChanged', onLangChange);
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
    <time dateTime={d.toISOString()} title={d.toLocaleString(i18n.language)} className="cursor-help">
      {formatRelativeTime(d)}
    </time>
  );
}
