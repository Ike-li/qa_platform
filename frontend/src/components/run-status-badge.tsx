import { useTranslation } from "react-i18next";
import { cn } from "../lib/utils";
import type { RunStatus } from "../types/api";

const statusStyles: Record<RunStatus, string> = {
  queued: "bg-status-queued/10 text-status-queued border-status-queued/20",
  preparing: "bg-status-running/10 text-status-running border-status-running/20",
  running: "bg-status-running/10 text-status-running border-status-running/20 animate-pulse",
  collecting: "bg-status-running/10 text-status-running border-status-running/20",
  passed: "bg-status-passed/10 text-status-passed border-status-passed/20",
  failed: "bg-status-failed/10 text-status-failed border-status-failed/20",
  cancelled: "bg-status-cancelled/10 text-status-cancelled border-status-cancelled/20",
  timed_out: "bg-status-failed/10 text-status-failed border-status-failed/20",
};

export function RunStatusBadge({ status, className }: { status: RunStatus; className?: string }) {
  const { t } = useTranslation();
  return (
    <span className={cn(
      "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium capitalize",
      statusStyles[status],
      className
    )}>
      {t(`runStatus.${status}`)}
    </span>
  );
}
