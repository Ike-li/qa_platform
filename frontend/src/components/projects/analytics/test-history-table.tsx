import { useTranslation } from "react-i18next";
import type { TestHistoryPoint } from "../../../types/api";
import { formatDateTime, historyStatusClass } from "./helpers";

export function TestHistoryTable({ data }: { data: TestHistoryPoint[] }) {
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
