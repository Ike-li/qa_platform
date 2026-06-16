import * as React from "react";
import { AlertCircle, ChevronRight, Flame, Repeat, Ban } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/utils";
import { TestStatusIcon } from "../test-status-icon";
import { useRunTriage } from "../../hooks/use-runs";
import type { TriageCluster, TriageItem, TriageObservation } from "../../types/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import api from "../../lib/api";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

const HISTORY_SLOTS = 10;

interface TriageGroupConfig {
  key: "new" | "knownFlaky" | "persistent";
  icon: typeof AlertCircle;
  tone: string;
  clusters: TriageCluster[];
  defaultOpen: boolean;
}

export function FailureTriagePanel({ runId, projectId }: { runId: string; projectId?: string }) {
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
          <TriageGroup key={group.key} group={group} projectId={projectId} runId={runId} />
        ))}
    </section>
  );
}

function TriageGroup({ group, projectId, runId }: { group: TriageGroupConfig; projectId?: string; runId: string }) {
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
        <ChevronRight className={cn("h-4 w-4 text-ink-tertiary transition-transform duration-200", open && "rotate-90")} />
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
            <TriageClusterBlock key={cluster.signature} cluster={cluster} projectId={projectId} runId={runId} />
          ))}
        </div>
      )}
    </div>
  );
}

function TriageClusterBlock({ cluster, projectId, runId }: { cluster: TriageCluster; projectId?: string; runId: string }) {
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
          <TriageItemRow key={`${item.suite}::${item.name}`} item={item} projectId={projectId} runId={runId} />
        ))}
      </div>
    </div>
  );
}

function TriageItemRow({ item, projectId, runId }: { item: TriageItem; projectId?: string; runId: string }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const queryClient = useQueryClient();

  const handleAddQuarantine = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectId) return;
    setIsSubmitting(true);
    try {
      await api.post(`/projects/${projectId}/quarantine`, {
        suite: item.suite,
        name: item.name,
        reason: reason.trim() || "Manual quarantine from FailureTriagePanel",
      });
      toast.success(t("runs.failureTriage.quarantineSuccess", "隔离用例成功"));
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["runs", runId, "triage"] });
    } catch (err: unknown) {
      const error = err as { response?: { status?: number; data?: { detail?: string } } };
      if (error.response?.status === 403) {
        toast.error(t("runs.failureTriage.noPermission", "无权限：仅项目管理员可操作"));
      } else {
        toast.error(error.response?.data?.detail || t("runs.failureTriage.quarantineFailed", "隔离用例失败"));
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemoveQuarantine = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!projectId) return;
    try {
      await api.delete(`/projects/${projectId}/quarantine`, {
        params: {
          suite: item.suite,
          name: item.name,
        },
      });
      toast.success(t("runs.failureTriage.unquarantineSuccess", "解除隔离成功"));
      queryClient.invalidateQueries({ queryKey: ["runs", runId, "triage"] });
    } catch (err: unknown) {
      const error = err as { response?: { status?: number; data?: { detail?: string } } };
      if (error.response?.status === 403) {
        toast.error(t("runs.failureTriage.noPermission", "无权限：仅项目管理员可操作"));
      } else {
        toast.error(error.response?.data?.detail || t("runs.failureTriage.unquarantineFailed", "解除隔离失败"));
      }
    }
  };

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
        {item.quarantined && (
          <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-xs font-semibold text-amber-600 dark:text-amber-400">
            <Ban className="h-3 w-3" />
            {t("runs.failureTriage.quarantined", "已隔离")}
          </span>
        )}
        <span className="ml-auto">
          <HistoryStrip history={item.recent_history} />
        </span>
      </div>
      {expanded && (
        <div className="mt-2 rounded-md border border-status-failed/20 bg-status-failed/5 p-3 space-y-3">
          {/* Quarantine Control Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-status-failed/10 pb-3">
            <div className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
              <span>
                {item.quarantined
                  ? t("runs.failureTriage.statusQuarantined", "当前状态：已隔离 (不会计入轻量发布指标)")
                  : t("runs.failureTriage.statusNormal", "当前状态：正常 (会影响发布门禁)")}
              </span>
            </div>
            {item.quarantined ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 text-xs border-amber-500/30 text-amber-600 hover:bg-amber-500/10 dark:text-amber-400"
                onClick={handleRemoveQuarantine}
              >
                {t("runs.failureTriage.unquarantine", "解除隔离")}
              </Button>
            ) : (
              projectId && (
                <form onSubmit={handleAddQuarantine} className="flex items-center gap-2 flex-1 max-w-md">
                  <Input
                    type="text"
                    placeholder={t("runs.failureTriage.reasonPlaceholder", "输入隔离原因 (选填)")}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    className="h-7 text-xs bg-canvas flex-1"
                    disabled={isSubmitting}
                  />
                  <Button
                    type="submit"
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs border-status-failed/30 text-status-failed hover:bg-status-failed/10 shrink-0"
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? t("runs.failureTriage.quarantining", "隔离中...") : t("runs.failureTriage.quarantine", "隔离用例")}
                  </Button>
                </form>
              )
            )}
          </div>

          <div>
            <p className="text-xs font-semibold text-status-failed">
              {item.error_message || t("runs.failureTriage.noMessage")}
            </p>
            {item.stack_trace && (
              <pre className="mt-2 max-h-[300px] overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-ink-muted">
                {item.stack_trace}
              </pre>
            )}
          </div>
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
