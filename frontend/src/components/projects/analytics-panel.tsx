import { useState, useId } from "react";
import { useTranslation } from "react-i18next";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useTrends, useFlakyTests, useTestHistory, useReleaseSummary } from "../../hooks/use-analytics";
import type { TrendDataPoint, FlakyTest, TestHistoryPoint, ReleaseSummary, ReleaseTestDelta } from "../../types/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";

const PERIOD_OPTIONS = [7, 14, 30, 90];

function TrendChart({ data }: { data: TrendDataPoint[] }) {
  const { t } = useTranslation();
  const uid = useId();

  if (data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-ink-tertiary">
        {t("analytics.noTrends")}
      </div>
    );
  }

  const chartData = data.map((d) => ({
    ...d,
    pass_rate_pct: Math.round(d.pass_rate * 100),
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`${uid}-gp`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-status-passed)" stopOpacity={0.3} />
            <stop offset="95%" stopColor="var(--color-status-passed)" stopOpacity={0} />
          </linearGradient>
          <linearGradient id={`${uid}-gf`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-status-failed)" stopOpacity={0.3} />
            <stop offset="95%" stopColor="var(--color-status-failed)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-hairline)" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 12, fill: "var(--color-ink-muted)" }}
          tickFormatter={(v: string) => v.slice(5)}
        />
        <YAxis
          yAxisId="count"
          tick={{ fontSize: 12, fill: "var(--color-ink-muted)" }}
          allowDecimals={false}
        />
        <YAxis
          yAxisId="rate"
          orientation="right"
          domain={[0, 100]}
          tick={{ fontSize: 12, fill: "var(--color-ink-muted)" }}
          tickFormatter={(v: number) => `${v}%`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--color-surface-1)",
            border: "1px solid var(--color-hairline)",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelFormatter={(label) => String(label ?? "")}
          formatter={(value, name) => {
            const metricName = String(name);
            const metricValue = typeof value === "number" || typeof value === "string" ? String(value) : "-";
            if (metricName === "pass_rate_pct") {
              return [metricValue === "-" ? metricValue : `${metricValue}%`, t("analytics.passRate")];
            }
            if (metricName === "passed_runs") return [metricValue, t("analytics.passed")];
            if (metricName === "failed_runs") return [metricValue, t("analytics.failed")];
            return [metricValue, metricName];
          }}
        />
        <Legend
          formatter={(value: string) => {
            if (value === "pass_rate_pct") return t("analytics.passRate");
            if (value === "passed_runs") return t("analytics.passed");
            if (value === "failed_runs") return t("analytics.failed");
            return value;
          }}
        />
        <Area
          yAxisId="count"
          type="monotone"
          dataKey="passed_runs"
          stroke="var(--color-status-passed)"
          fill={`url(#${uid}-gp)`}
          strokeWidth={2}
        />
        <Area
          yAxisId="count"
          type="monotone"
          dataKey="failed_runs"
          stroke="var(--color-status-failed)"
          fill={`url(#${uid}-gf)`}
          strokeWidth={2}
        />
        <Area
          yAxisId="rate"
          type="monotone"
          dataKey="pass_rate_pct"
          stroke="var(--color-primary)"
          fill="none"
          strokeWidth={2}
          strokeDasharray="6 3"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function testKey(test: Pick<FlakyTest, "suite" | "name">) {
  return `${test.suite}\u0000${test.name}`;
}

function FlakyTable({
  data,
  selectedKey,
  onSelect,
}: {
  data: FlakyTest[];
  selectedKey: string | null;
  onSelect: (test: FlakyTest) => void;
}) {
  const { t } = useTranslation();

  if (data.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-ink-tertiary">
        {t("analytics.noFlaky")}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-hairline text-left text-xs text-ink-muted">
            <th className="pb-3 pr-4 font-medium">{t("analytics.suite")}</th>
            <th className="pb-3 pr-4 font-medium">{t("analytics.testCase")}</th>
            <th className="pb-3 pr-4 font-medium text-right">{t("analytics.runs")}</th>
            <th className="pb-3 pr-4 font-medium text-right">{t("analytics.failures")}</th>
            <th className="pb-3 pr-4 font-medium text-right">{t("analytics.flakyRate")}</th>
            <th className="pb-3 font-medium text-right">{t("analytics.history")}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((test, i) => {
            const key = testKey(test);
            return (
              <tr key={`${test.suite}-${test.name}-${i}`} className="border-b border-hairline/50">
                <td className="py-3 pr-4 text-ink-muted font-mono text-xs max-w-[200px] truncate" title={test.suite}>
                  {test.suite}
                </td>
                <td className="py-3 pr-4 font-medium text-ink max-w-[300px] truncate" title={test.name}>
                  {test.name}
                </td>
                <td className="py-3 pr-4 text-right tabular-nums">{test.total_runs}</td>
                <td className="py-3 pr-4 text-right tabular-nums text-status-failed">
                  {test.failed_count}
                </td>
                <td className="py-3 pr-4 text-right">
                  <span
                    className={
                      test.flaky_rate > 0.5
                        ? "text-status-failed font-medium"
                        : test.flaky_rate > 0.2
                          ? "text-status-running"
                          : "text-ink-muted"
                    }
                  >
                    {Math.round(test.flaky_rate * 100)}%
                  </span>
                </td>
                <td className="py-3 text-right">
                  <Button
                    type="button"
                    variant={selectedKey === key ? "default" : "outline"}
                    size="sm"
                    onClick={() => onSelect(test)}
                  >
                    {t("analytics.history")}
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString();
}

function historyStatusClass(status: TestHistoryPoint["status"]) {
  if (status === "passed") return "text-status-passed";
  if (status === "failed" || status === "error") return "text-status-failed";
  if (status === "skipped" || status === "xfail") return "text-status-skipped";
  return "text-ink-muted";
}

function TestHistoryTable({ data }: { data: TestHistoryPoint[] }) {
  const { t } = useTranslation();

  if (data.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center text-sm text-ink-tertiary">
        {t("analytics.noHistory")}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-hairline text-left text-xs text-ink-muted">
            <th className="pb-3 pr-4 font-medium">{t("analytics.run")}</th>
            <th className="pb-3 pr-4 font-medium">{t("analytics.status")}</th>
            <th className="pb-3 pr-4 font-medium">{t("analytics.gitRef")}</th>
            <th className="pb-3 pr-4 font-medium text-right">{t("analytics.durationMs")}</th>
            <th className="pb-3 font-medium">{t("analytics.error")}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((point) => (
            <tr key={point.run_id} className="border-b border-hairline/50">
              <td className="py-3 pr-4">
                <div className="font-mono text-xs text-ink">{point.run_id.slice(0, 8)}</div>
                <div className="text-xs text-ink-tertiary">{formatDateTime(point.run_created_at)}</div>
              </td>
              <td className={`py-3 pr-4 font-medium ${historyStatusClass(point.status)}`}>
                {t(`analytics.status.${point.status}`)}
              </td>
              <td className="py-3 pr-4 font-mono text-xs text-ink-muted max-w-[220px] truncate" title={point.git_ref ?? ""}>
                {point.git_ref ?? "-"}
              </td>
              <td className="py-3 pr-4 text-right tabular-nums">{point.duration_ms ?? "-"}</td>
              <td className="py-3 text-ink-muted max-w-[320px] truncate" title={point.error_message ?? ""}>
                {point.error_message ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatPercent(value: number | null) {
  if (value === null) return "-";
  return `${Math.round(value * 100)}%`;
}

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

function ReleaseSummaryPanel({
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

export function AnalyticsPanel({
  projectId,
  defaultBranch,
  initialSuite,
  initialTest,
}: {
  projectId: string;
  defaultBranch: string;
  initialSuite?: string;
  initialTest?: string;
}) {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const [selectedTestKey, setSelectedTestKey] = useState<string | null>(null);
  const [gitRefInput, setGitRefInput] = useState("");
  const [baselineRefInput, setBaselineRefInput] = useState("");
  const selectedGitRef = gitRefInput.trim() || defaultBranch;
  const baselineGitRef = baselineRefInput.trim() || defaultBranch;
  const initialHistoryTest = initialSuite && initialTest
    ? { suite: initialSuite, name: initialTest }
    : null;
  const initialHistoryKey = initialHistoryTest ? testKey(initialHistoryTest) : null;

  const { data: trends, isLoading: trendsLoading, isError: trendsError } = useTrends(projectId, days, selectedGitRef);
  const { data: flaky, isLoading: flakyLoading, isError: flakyError } = useFlakyTests(projectId, days, 3, selectedGitRef);
  const {
    data: releaseSummary,
    isLoading: releaseLoading,
    isError: releaseError,
  } = useReleaseSummary(projectId, days, selectedGitRef, baselineGitRef);
  const effectiveSelectedTestKey = selectedTestKey ?? initialHistoryKey;
  const selectedTest =
    (effectiveSelectedTestKey ? flaky?.find((test) => testKey(test) === effectiveSelectedTestKey) : null)
    ?? (effectiveSelectedTestKey === initialHistoryKey ? initialHistoryTest : null)
    ?? flaky?.[0]
    ?? null;
  const { data: history, isLoading: historyLoading, isError: historyError } = useTestHistory(
    projectId,
    selectedTest?.suite,
    selectedTest?.name,
    days,
  );

  return (
    <div className="space-y-8">
      {/* Period selector */}
      <div className="flex flex-col gap-3 rounded-xl border border-hairline bg-surface-1 p-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label className="text-xs font-medium text-ink-muted">{t("analytics.release.targetRef")}</label>
            <Input
              value={gitRefInput}
              onChange={(event) => setGitRefInput(event.target.value)}
              placeholder={defaultBranch}
              className="w-full sm:w-64"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-ink-muted">{t("analytics.release.baselineRef")}</label>
            <Input
              value={baselineRefInput}
              onChange={(event) => setBaselineRefInput(event.target.value)}
              placeholder={defaultBranch}
              className="w-full sm:w-64"
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-ink-muted">{t("analytics.daysPeriod")}:</span>
          {PERIOD_OPTIONS.map((d) => (
            <Button
              key={d}
              variant={d === days ? "default" : "outline"}
              size="sm"
              aria-pressed={d === days}
              onClick={() => setDays(d)}
            >
              {d}d
            </Button>
          ))}
        </div>
      </div>

      <ReleaseSummaryPanel
        summary={releaseSummary}
        isLoading={releaseLoading}
        isError={releaseError}
      />

      {/* Trends chart */}
      <div className="rounded-xl border border-hairline bg-surface-1 p-6">
        <div className="mb-4">
          <h3 className="text-lg font-medium text-ink">{t("analytics.trendsTitle")}</h3>
          <p className="text-sm text-ink-muted">{t("analytics.trendsDescription")}</p>
        </div>
        {trendsLoading ? (
          <div className="h-[300px] animate-pulse rounded bg-surface-2" />
        ) : trendsError ? (
          <div className="flex h-[300px] items-center justify-center text-sm text-status-failed">
            {t("analytics.loadError")}
          </div>
        ) : (
          <TrendChart data={trends ?? []} />
        )}
      </div>

      {/* Flaky tests */}
      <div className="rounded-xl border border-hairline bg-surface-1 p-6">
        <div className="mb-4">
          <h3 className="text-lg font-medium text-ink">{t("analytics.flakyTitle")}</h3>
          <p className="text-sm text-ink-muted">{t("analytics.flakyDescription")}</p>
        </div>
        {flakyLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-10 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        ) : flakyError ? (
          <div className="flex h-[200px] items-center justify-center text-sm text-status-failed">
            {t("analytics.loadError")}
          </div>
        ) : (
          <FlakyTable
            data={flaky ?? []}
            selectedKey={selectedTest ? testKey(selectedTest) : null}
            onSelect={(test) => setSelectedTestKey(testKey(test))}
          />
        )}
      </div>

      {selectedTest && (
        <div className="rounded-xl border border-hairline bg-surface-1 p-6">
          <div className="mb-4">
            <h3 className="text-lg font-medium text-ink">{t("analytics.historyTitle")}</h3>
            <p className="text-sm text-ink-muted">
              {selectedTest.suite} / {selectedTest.name}
            </p>
          </div>
          {historyLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 animate-pulse rounded bg-surface-2" />
              ))}
            </div>
          ) : historyError ? (
            <div className="flex h-[180px] items-center justify-center text-sm text-status-failed">
              {t("analytics.loadError")}
            </div>
          ) : (
            <TestHistoryTable data={history ?? []} />
          )}
        </div>
      )}
    </div>
  );
}
