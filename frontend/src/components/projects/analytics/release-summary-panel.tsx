import { useTranslation } from "react-i18next";
import type { ReleaseSummary, ReleaseTestDelta } from "../../../types/api";
import { formatPercent } from "./helpers";

function DeltaList({ data }: { data: ReleaseTestDelta[] }) {
  if (data.length === 0) {
    return <span className="text-sm text-ink-tertiary">-</span>;
  }
  return (
    <div className="space-y-2">
      {data.slice(0, 5).map((test) => (
        <div key={`${test.suite}:${test.name}`} className="min-w-0">
          <div className="truncate text-sm font-medium text-ink" title={test.name}>
            {test.name}
          </div>
          <div className="truncate text-xs text-ink-muted" title={test.suite}>
            {test.suite} · {test.failed_count}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ReleaseSummaryPanel({
  summary,
  isLoading,
  isError,
}: {
  summary: ReleaseSummary | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const { t } = useTranslation();

  if (isLoading) {
    return <div className="h-40 animate-pulse rounded-xl border border-hairline bg-surface-1" />;
  }

  if (isError || !summary) {
    return (
      <div className="rounded-xl border border-hairline bg-surface-1 p-6 text-sm text-status-failed">
        {t("analytics.release.loadError")}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-hairline bg-surface-1 p-6">
      <div className="mb-4 flex flex-col gap-1">
        <h3 className="text-lg font-medium text-ink">{t("analytics.release.title")}</h3>
        <p className="text-sm text-ink-muted">
          {summary.git_ref} {t("analytics.release.comparedWith")} {summary.baseline_git_ref}
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border border-hairline bg-surface-2/40 p-4">
          <div className="text-xs uppercase text-ink-tertiary">{t("analytics.totalRuns")}</div>
          <div className="mt-1 text-2xl font-semibold text-ink">{summary.total_runs}</div>
        </div>
        <div className="rounded-lg border border-status-passed/20 bg-status-passed/5 p-4">
          <div className="text-xs uppercase text-status-passed/80">{t("analytics.passRate")}</div>
          <div className="mt-1 text-2xl font-semibold text-status-passed">
            {formatPercent(summary.raw_pass_rate)}
          </div>
        </div>
        <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
          <div className="text-xs uppercase text-primary/80">{t("analytics.release.adjustedPassRate")}</div>
          <div className="mt-1 text-2xl font-semibold text-primary">
            {formatPercent(summary.flaky_adjusted_pass_rate)}
          </div>
        </div>
        <div className="rounded-lg border border-status-failed/20 bg-status-failed/5 p-4">
          <div className="text-xs uppercase text-status-failed/80">{t("analytics.failed")}</div>
          <div className="mt-1 text-2xl font-semibold text-status-failed">{summary.failed_runs}</div>
        </div>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-hairline bg-surface-2/30 p-4">
          <h4 className="mb-3 text-sm font-medium text-ink">{t("analytics.release.newFailures")}</h4>
          <DeltaList data={summary.new_failing_tests} />
        </div>
        <div className="rounded-lg border border-hairline bg-surface-2/30 p-4">
          <h4 className="mb-3 text-sm font-medium text-ink">{t("analytics.release.recovered")}</h4>
          <DeltaList data={summary.recovered_tests} />
        </div>
      </div>
    </div>
  );
}
