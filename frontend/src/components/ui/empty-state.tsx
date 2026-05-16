import * as React from "react"
import { cn } from "../../lib/utils"
import { Button } from "./button"

interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export function EmptyState({ className, icon, title, description, action, ...props }: EmptyStateProps) {
  return (
    <div 
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-hairline border-dashed p-12 text-center",
        className
      )}
      {...props}
    >
      {icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-1 text-ink-tertiary mb-4">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-medium text-ink">{title}</h3>
      {description && <p className="mt-2 text-sm text-ink-subtle max-w-sm">{description}</p>}
      {action && (
        <Button variant="outline" className="mt-6" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  )
}
