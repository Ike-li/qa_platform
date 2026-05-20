import { useTranslation } from "react-i18next";
import { cn } from "../lib/utils";

const priorityStyles: Record<number, string> = {
  0: "bg-red-500/10 text-red-600 border-red-500/20",
  1: "bg-yellow-500/10 text-yellow-600 border-yellow-500/20",
  2: "bg-gray-500/10 text-gray-500 border-gray-500/20",
};

const priorityKeys: Record<number, string> = {
  0: "priority.high",
  1: "priority.medium",
  2: "priority.low",
};

export function PriorityBadge({ priority, className }: { priority: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <span className={cn(
      "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium capitalize",
      priorityStyles[priority] ?? priorityStyles[1],
      className
    )}>
      {t(priorityKeys[priority] ?? "priority.medium")}
    </span>
  );
}
