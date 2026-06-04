import * as React from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight, History } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/utils";
import { TestStatusIcon } from "./test-status-icon";
import type { TestResult } from "../types/api";

interface TestResultsTableProps {
  results: TestResult[];
  isLoading?: boolean;
  projectId?: string;
}

export function TestResultsTable({ results, isLoading, projectId }: TestResultsTableProps) {
  const { t } = useTranslation();

  return (
    <div className="rounded-xl border border-hairline bg-surface-1 overflow-hidden">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-hairline bg-surface-2/50 text-ink-muted">
            <th className="w-10 px-4 py-3"></th>
            <th className="px-4 py-3 font-medium">{t('runs.results.testCase')}</th>
            <th className="px-4 py-3 font-medium">{t('runs.results.suite')}</th>
            <th className="px-4 py-3 font-medium">{t('runs.results.status')}</th>
            <th className="px-4 py-3 font-medium">{t('runs.results.duration')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline">
          {isLoading ? (
            [1, 2, 3].map(i => (
              <tr key={i} className="animate-pulse">
                <td colSpan={5} className="p-4">
                  <div className="h-4 w-full bg-surface-2 rounded" />
                </td>
              </tr>
            ))
          ) : results.length === 0 ? (
            <tr>
              <td colSpan={5} className="p-12 text-center text-ink-tertiary">
                {t('runs.results.noResults')}
              </td>
            </tr>
          ) : (
            results.map(result => (
              <TestResultRow key={result.id} result={result} projectId={projectId} />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function TestResultRow({ result, projectId }: { result: TestResult; projectId?: string }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const isFailed = result.status === "failed" || result.status === "error";
  const historySearch = new URLSearchParams({
    tab: "analytics",
    suite: result.suite,
    test: result.name,
  }).toString();

  return (
    <>
      <tr
        className={cn(
          "group hover:bg-surface-2/50 transition-colors",
          isFailed && "cursor-pointer",
          expanded && "bg-surface-2/30"
        )}
        onClick={() => isFailed && setExpanded(!expanded)}
        onKeyDown={(e) => isFailed && (e.key === "Enter" || e.key === " ") && setExpanded(!expanded)}
        tabIndex={isFailed ? 0 : undefined}
        role={isFailed ? "button" : undefined}
        aria-expanded={isFailed ? expanded : undefined}
      >
        <td className="px-4 py-3 text-center">
          {isFailed && (
            expanded
              ? <ChevronDown className="h-4 w-4 text-ink-tertiary" />
              : <ChevronRight className="h-4 w-4 text-ink-tertiary" />
          )}
        </td>
        <td className="px-4 py-3 font-medium text-ink">{result.name}</td>
        <td className="px-4 py-3 text-ink-muted truncate max-w-[200px]">{result.suite}</td>
        <td className="px-4 py-3">
          <span className={cn(
            "inline-flex items-center gap-1.5 text-xs font-medium",
            result.status === "passed" && "text-status-passed",
            isFailed && "text-status-failed",
            (result.status === "skipped" || result.status === "xfail") && "text-status-skipped"
          )}>
            <TestStatusIcon status={result.status} className="h-3 w-3" />
            {t('testStatus.' + result.status)}
          </span>
        </td>
        <td className="px-4 py-3 text-ink-tertiary">{result.duration_ms}ms</td>
      </tr>
      {expanded && isFailed && (
        <tr>
          <td colSpan={5} className="bg-surface-2/20 px-8 py-4">
            <div className="rounded-md border border-status-failed/20 bg-status-failed/5 p-4 space-y-3">
              <p className="font-semibold text-status-failed text-sm">
                {result.error_message || t('runs.results.unknownError')}
              </p>
              {result.stack_trace && (
                <pre className="mt-2 overflow-x-auto font-mono text-xs text-ink-muted leading-relaxed whitespace-pre-wrap max-h-[300px]">
                  {result.stack_trace}
                </pre>
              )}
              {projectId && (
                <Link
                  to={`/projects/${projectId}?${historySearch}`}
                  className="inline-flex items-center gap-2 rounded-md border border-hairline bg-surface-1 px-3 py-2 text-xs font-medium text-ink transition-colors hover:border-primary/40 hover:text-primary"
                >
                  <History className="h-3.5 w-3.5" />
                  {t("runs.results.viewHistory")}
                </Link>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
