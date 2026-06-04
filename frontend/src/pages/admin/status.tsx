import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";

interface SystemStatus {
  queue_depth: number;
  in_flight: number;
  success_rate_1h: number;
  total_runs_1h: number;
}

function StatusCard({
  label,
  value,
  subtext,
}: {
  label: string;
  value: string | number;
  subtext?: string;
}) {
  return (
    <div className="rounded-xl border border-hairline bg-surface-1 p-6">
      <p className="text-sm text-ink-muted">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">
        {value}
      </p>
      {subtext && (
        <p className="mt-1 text-xs text-ink-tertiary">{subtext}</p>
      )}
    </div>
  );
}

export default function AdminStatus() {
  const { t } = useTranslation();

  const { data, isLoading, isError, refetch } = useQuery<SystemStatus>({
    queryKey: ["admin", "status"],
    queryFn: async () => {
      const { data } = await api.get<SystemStatus>("/admin/status");
      return data;
    },
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("admin.status.title", "System Status")}
        </h1>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-28 animate-pulse rounded-xl bg-surface-2"
            />
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("admin.status.title", "System Status")}
        </h1>
        <div className="flex h-[200px] flex-col items-center justify-center gap-4 text-sm text-status-failed">
          <p>{t("admin.status.error", "Failed to load system status")}</p>
          <Button variant="outline" onClick={() => void refetch()}>
            {t("common.retry", "Retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        {t("admin.status.title", "System Status")}
      </h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatusCard
          label={t("admin.status.queueDepth", "Queue Depth")}
          value={data?.queue_depth ?? 0}
        />
        <StatusCard
          label={t("admin.status.inFlight", "In Flight")}
          value={data?.in_flight ?? 0}
        />
        <StatusCard
          label={t("admin.status.successRate", "Success Rate (1h)")}
          value={`${((data?.success_rate_1h ?? 1) * 100).toFixed(1)}%`}
        />
        <StatusCard
          label={t("admin.status.totalRuns", "Total Runs (1h)")}
          value={data?.total_runs_1h ?? 0}
        />
      </div>
    </div>
  );
}
