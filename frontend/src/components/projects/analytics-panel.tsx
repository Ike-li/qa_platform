import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useFlakyTests, useReleaseSummary, useTestHistory, useTrends } from "../../hooks/use-analytics";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { FlakyTable } from "./analytics/flaky-table";
import { PERIOD_OPTIONS, testKey } from "./analytics/helpers";
import { ReleaseSummaryPanel } from "./analytics/release-summary-panel";
import { TestHistoryTable } from "./analytics/test-history-table";
import { TrendChart } from "./analytics/trend-chart";

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
  const [collapseParams, setCollapseParams] = useState(false);
  const selectedGitRef = gitRefInput.trim() || defaultBranch;
  const baselineGitRef = baselineRefInput.trim() || defaultBranch;
  const initialHistoryTest = initialSuite && initialTest
    ? { suite: initialSuite, name: initialTest }
    : null;
  const initialHistoryKey = initialHistoryTest ? testKey(initialHistoryTest) : null;

  const { data: trends, isLoading: trendsLoading, isError: trendsError } = useTrends(projectId, days, selectedGitRef);
  const { data: flaky, isLoading: flakyLoading, isError: flakyError } = useFlakyTests(
    projectId,
    days,
    3,
    selectedGitRef,
    collapseParams,
  );
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
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h3 className="text-lg font-medium text-ink">{t("analytics.flakyTitle")}</h3>
            <p className="text-sm text-ink-muted">{t("analytics.flakyDescription")}</p>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={collapseParams}
              onChange={(e) => setCollapseParams(e.target.checked)}
              className="h-4 w-4 rounded border-hairline text-primary-600 focus:ring-2 focus:ring-primary-500"
            />
            <span>{t("analytics.collapseParams")}</span>
          </label>
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
