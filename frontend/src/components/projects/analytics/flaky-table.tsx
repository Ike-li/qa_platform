import { useTranslation } from "react-i18next";
import type { FlakyTest } from "../../../types/api";
import { Button } from "../../ui/button";
import { testKey } from "./helpers";

export function FlakyTable({
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
