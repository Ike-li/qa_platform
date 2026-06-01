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
import { useTrends, useFlakyTests, useTestHistory } from "../../hooks/use-analytics";
import type { TrendDataPoint, FlakyTest, TestHistoryPoint } from "../../types/api";
import { Button } from "../ui/button";

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

export function AnalyticsPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const [selectedTestKey, setSelectedTestKey] = useState<string | null>(null);

  const { data: trends, isLoading: trendsLoading, isError: trendsError } = useTrends(projectId, days);
  const { data: flaky, isLoading: flakyLoading, isError: flakyError } = useFlakyTests(projectId, days);
  const selectedTest =
    (selectedTestKey ? flaky?.find((test) => testKey(test) === selectedTestKey) : null) ?? flaky?.[0] ?? null;
  const { data: history, isLoading: historyLoading, isError: historyError } = useTestHistory(
    projectId,
    selectedTest?.suite,
    selectedTest?.name,
    days,
  );

  return (
    <div className="space-y-8">
      {/* Period selector */}
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
