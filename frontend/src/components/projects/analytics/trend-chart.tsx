import { useId } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TrendDataPoint } from "../../../types/api";

export function TrendChart({ data }: { data: TrendDataPoint[] }) {
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
