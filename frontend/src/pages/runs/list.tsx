import { useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Clock,
  User,
  ArrowRight
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useRuns } from "../../hooks/use-runs";
import { RunStatusBadge } from "../../components/run-status-badge";
import { PriorityBadge } from "../../components/priority-badge";
import { BranchBadge } from "../../components/branch-badge";
import { DurationDisplay } from "../../components/duration-display";
import { RelativeTime } from "../../components/relative-time";
import { Skeleton } from "../../components/ui/skeleton";
import { EmptyState } from "../../components/ui/empty-state";
import { Button } from "../../components/ui/button";
import { usePageTitle } from "../../hooks/use-page-title";

export default function Runs() {
  const { t } = useTranslation();
  usePageTitle(t('runs.title'));
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, parseInt(searchParams.get("page") || "1", 10));

  const setPage = useCallback((updater: number | ((prev: number) => number)) => {
    setSearchParams(prev => {
      const next = typeof updater === "function" ? updater(parseInt(prev.get("page") || "1", 10)) : updater;
      if (next <= 1) {
        prev.delete("page");
      } else {
        prev.set("page", String(next));
      }
      return prev;
    }, { replace: true });
  }, [setSearchParams]);

  const { data, isLoading, isError } = useRuns({ per_page: 20, page });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t('runs.title')}</h1>
          <p className="text-sm text-ink-subtle">{t('runs.subtitle')}</p>
        </div>
      </div>

      {isError && (
        <div className="rounded-xl border border-status-failed/20 bg-status-failed/5 p-6 text-center">
          <p className="text-sm text-status-failed">{t('runs.failedToLoad')}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => setPage(1)}>{t('common.retry')}</Button>
        </div>
      )}

      {!isError && (
      <div className="rounded-xl border border-hairline bg-surface-1 overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-hairline bg-surface-2/50 text-ink-muted">
              <th className="px-6 py-3 font-medium">{t('runs.table.status')}</th>
              <th className="px-6 py-3 font-medium">{t('trigger.priority')}</th>
              <th className="px-6 py-3 font-medium">{t('runs.table.pipeline')}</th>
              <th className="px-6 py-3 font-medium">{t('runs.table.branch')}</th>
              <th className="px-6 py-3 font-medium">{t('runs.table.triggeredBy')}</th>
              <th className="px-6 py-3 font-medium">{t('runs.table.duration')}</th>
              <th className="px-6 py-3 font-medium">{t('runs.table.started')}</th>
              <th className="px-6 py-3 font-medium text-right">{t('runs.table.action')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {isLoading ? (
              [1, 2, 3, 4, 5].map(i => (
                <tr key={i}>
                  <td className="px-6 py-4"><Skeleton className="h-5 w-20 rounded-full" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-5 w-16 rounded-full" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-36" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-24" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-28" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-20" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-24" /></td>
                  <td className="px-6 py-4 text-right">
                    <Skeleton className="ml-auto h-8 w-20" />
                  </td>
                </tr>
              ))
            ) : data?.data.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-0">
                  <EmptyState
                    title={t('runs.noRuns')}
                    description={t('runs.noRunsDescription')}
                    className="border-0 rounded-none rounded-b-xl"
                  />
                </td>
              </tr>
            ) : (
              data?.data.map(run => (
                <tr key={run.id} className="group hover:bg-surface-2/50 transition-colors">
                  <td className="px-6 py-4">
                    <RunStatusBadge status={run.status} />
                  </td>
                  <td className="px-6 py-4">
                    <PriorityBadge priority={run.priority} />
                  </td>
                  <td className="px-6 py-4 font-medium text-ink">
                    <Link to={`/runs/${run.id}`} className="hover:text-primary transition-colors">
                      {run.pipeline_name}
                    </Link>
                  </td>
                  <td className="px-6 py-4">
                    <BranchBadge branch={run.branch} />
                  </td>
                  <td className="px-6 py-4 text-ink-muted">
                    <div className="flex items-center gap-1.5">
                      <User className="h-3.5 w-3.5" />
                      <span>{run.triggered_by}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-ink-muted">
                    <div className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5" />
                      <DurationDisplay seconds={run.duration_seconds} />
                    </div>
                  </td>
                  <td className="px-6 py-4 text-ink-tertiary">
                    <RelativeTime date={run.created_at} />
                  </td>
                  <td className="px-6 py-4 text-right">
                    <Button variant="ghost" size="sm" asChild>
                      <Link to={`/runs/${run.id}`}>
                        {t('common.details')} <ArrowRight className="ml-2 h-3 w-3" />
                      </Link>
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      )}

      {data && data.total > data.per_page && (
        <div className="flex items-center justify-between px-2">
          <p className="text-xs text-ink-tertiary">{t('common.showingOf', { count: data.data.length, total: data.total })}</p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>{t('common.previous')}</Button>
            <Button variant="outline" size="sm" disabled={page * data.per_page >= data.total} onClick={() => setPage(p => p + 1)}>{t('common.next')}</Button>
          </div>
        </div>
      )}
    </div>
  );
}
