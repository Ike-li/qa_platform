import * as React from "react";
import { AlertCircle, ChevronDown, ChevronRight, Flame, Repeat } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/utils";
import { TestStatusIcon } from "../test-status-icon";
import { useRunTriage } from "../../hooks/use-runs";
import type { TriageCluster, TriageItem, TriageObservation } from "../../types/api";

const HISTORY_SLOTS = 10;

interface TriageGroupConfig {
  key: "new" | "knownFlaky" | "persistent";
  icon: typeof AlertCircle;
  tone: string;
  clusters: TriageCluster[];
  defaultOpen: boolean;
}

export function FailureTriagePanel({ runId }: { runId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useRunTriage(runId);

  if (isLoading) {
    return (
      <div
        data-testid="triage-loading"
        className="h-24 animate-pulse rounded-xl border border-hairline bg-surface-1"
      />
    );
  }

  // 空态：无失败时不显示分诊区。
  if (!data || data.total_failed === 0) return null;

  const groups: TriageGroupConfig[] = [
    {
      key: "new",
      icon: AlertCircle,
      tone: "text-status-failed",
      clusters: data.new,
      defaultOpen: true,
    },
    {
      key: "knownFlaky",
      icon: Repeat,
      tone: "text-status-running",
      clusters: data.known_flaky,
      defaultOpen: false,
    },
    {
      key: "persistent",
      icon: Flame,
      tone: "text-status-skipped",
      clusters: data.persistent,
      defaultOpen: false,
    },
  ];

  return (
    <section className="space-y-3" aria-label={t("runs.failureTriage.title")}>
      <h2 className="text-sm font-semibold text-ink">
        {t("runs.failureTriage.title")}
      </h2>
      {groups
        .filter((group) => group.clusters.length > 0)
        .map((group) => (
          <TriageGroup key={group.key} group={group} />
        ))}
    </section>
  );
}

function TriageGroup({ group }: { group: TriageGroupConfig }) {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(group.defaultOpen);
  const Icon = group.icon;
  const itemCount = group.clusters.reduce((sum, cluster) => sum + cluster.count, 0);
  const groupLabel = t(`runs.failureTriage.group.${group.key}`);

  return (
    <div className="overflow-hidden rounded-xl border border-hairline bg-surface-1">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-surface-2/50"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open
          ? <ChevronDown className="h-4 w-4 text-ink-tertiary" />
          : <ChevronRight className="h-4 w-4 text-ink-tertiary" />}
        <Icon className={cn("h-4 w-4", group.tone)} />
        <span className="text-sm font-medium text-ink">{groupLabel}</span>
        <span className={cn(
          "ml-1 rounded-full px-2 py-0.5 text-xs font-semibold",
          "bg-surface-2 text-ink-muted"
        )}>
          {itemCount}
        </span>
      </button>
      {open && (
        <div className="divide-y divide-hairline border-t border-hairline">
          {group.clusters.map((cluster) => (
            <TriageClusterBlock key={cluster.signature} cluster={cluster} />
          ))}
        </div>
      )}
    </div>
  );
}

function TriageClusterBlock({ cluster }: { cluster: TriageCluster }) {
  const { t } = useTranslation();

  return (
    <div className="px-4 py-2">
      <div className="flex items-baseline gap-2 py-1">
        <code className="truncate font-mono text-xs text-ink-muted" title={cluster.signature}>
          {cluster.signature}
        </code>
        {cluster.count > 1 && (
          <span className="shrink-0 rounded bg-surface-2 px-1.5 text-xs font-medium text-ink-muted">
            {t("runs.failureTriage.clusterCount", { count: cluster.count })}
          </span>
        )}
      </div>
      <div className="divide-y divide-hairline/60">
        {cluster.items.map((item) => (
          <TriageItemRow key={`${item.suite}::${item.name}`} item={item} />
        ))}
      </div>
    </div>
  );
}

function TriageItemRow({ item }: { item: TriageItem }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);

  return (
    <div className="py-2">
      <div
        className="flex cursor-pointer flex-wrap items-center gap-2"
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setExpanded(!expanded)}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
      >
        <TestStatusIcon status={item.status} className="h-3.5 w-3.5 shrink-0 text-status-failed" />
        <span className="text-sm font-medium text-ink">{item.name}</span>
        <span className="truncate text-xs text-ink-tertiary">{item.suite}</span>
        {item.confidence === "observing" && (
          <span className="rounded-full border border-hairline bg-surface-2 px-2 py-0.5 text-xs text-ink-muted">
            {t("runs.failureTriage.observing", { count: item.observation_count })}
          </span>
        )}
        <span className="ml-auto">
          <HistoryStrip history={item.recent_history} />
        </span>
      </div>
      {expanded && (
        <div className="mt-2 rounded-md border border-status-failed/20 bg-status-failed/5 p-3">
          <p className="text-xs font-semibold text-status-failed">
            {item.error_message || t("runs.failureTriage.noMessage")}
          </p>
          {item.stack_trace && (
            <pre className="mt-2 max-h-[300px] overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-ink-muted">
              {item.stack_trace}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function historySlotClass(status: TriageObservation["status"]): string {
  if (status === "passed") return "bg-status-passed";
  if (status === "failed" || status === "error") return "bg-status-failed";
  return "bg-status-skipped";
}

function HistoryStrip({ history }: { history: TriageObservation[] }) {
  const { t } = useTranslation();
  const padding = Math.max(0, HISTORY_SLOTS - history.length);

  return (
    <span
      className="inline-flex items-center gap-0.5"
      aria-label={t("runs.failureTriage.historyLabel")}
      data-testid="history-strip"
    >
      {Array.from({ length: padding }).map((_, i) => (
        <span
          key={`pad-${i}`}
          className="h-3 w-1.5 rounded-sm border border-hairline bg-transparent"
        />
      ))}
      {history.map((obs) => (
        <span
          key={obs.run_id}
          title={`${obs.status} · ${new Date(obs.run_created_at).toLocaleString()}`}
          className={cn("h-3 w-1.5 rounded-sm", historySlotClass(obs.status))}
        />
      ))}
    </span>
  );
}
