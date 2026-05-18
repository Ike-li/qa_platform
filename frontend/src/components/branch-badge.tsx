import { GitBranch } from "lucide-react";
import { cn } from "../lib/utils";

export function BranchBadge({ branch, className }: { branch: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm text-ink-muted", className)}>
      <GitBranch className="h-3.5 w-3.5" />
      <span>{branch}</span>
    </span>
  );
}
