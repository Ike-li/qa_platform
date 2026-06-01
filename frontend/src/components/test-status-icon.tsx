import { CheckCircle2, XCircle, AlertCircle, SkipForward, HelpCircle } from "lucide-react";
import { cn } from "../lib/utils";

type TestStatus = "passed" | "failed" | "error" | "skipped" | "xfail";

const statusConfig: Record<TestStatus, { icon: typeof CheckCircle2; color: string }> = {
  passed: { icon: CheckCircle2, color: "text-status-passed" },
  failed: { icon: XCircle, color: "text-status-failed" },
  error: { icon: AlertCircle, color: "text-status-failed" },
  skipped: { icon: SkipForward, color: "text-status-skipped" },
  xfail: { icon: AlertCircle, color: "text-status-skipped" },
};

export function TestStatusIcon({ status, className }: { status: string; className?: string }) {
  const config = (statusConfig as Record<string, { icon: typeof CheckCircle2; color: string }>)[status]
    ?? { icon: HelpCircle, color: "text-ink-tertiary" };
  const Icon = config.icon;
  return <Icon className={cn("h-4 w-4", config.color, className)} />;
}
