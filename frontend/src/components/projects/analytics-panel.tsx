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
import { useTrends, useFlakyTests } from "../../hooks/use-analytics";
import type { TrendDataPoint, FlakyTest } from "../../types/api";
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

function FlakyTable({ data }: { data: FlakyTest[] }) {
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
            <th className="pb-3 font-medium text-right">{t("analytics.flakyRate")}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((test, i) => (
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
              <td className="py-3 text-right">
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

  const { data: trends, isLoading: trendsLoading, isError: trendsError } = useTrends(projectId, days);
  const { data: flaky, isLoading: flakyLoading, isError: flakyError } = useFlakyTests(projectId, days);

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
          <FlakyTable data={flaky ?? []} />
        )}
      </div>
    </div>
  );
}
