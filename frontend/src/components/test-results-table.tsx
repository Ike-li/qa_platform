import * as React from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/utils";
import { TestStatusIcon } from "./test-status-icon";
import type { TestResult } from "../types/api";

interface TestResultsTableProps {
  results: TestResult[];
  isLoading?: boolean;
}

export function TestResultsTable({ results, isLoading }: TestResultsTableProps) {
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
              <TestResultRow key={result.id} result={result} />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function TestResultRow({ result }: { result: TestResult }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const isFailed = result.status === "failed" || result.status === "error";

  return (
    <>
      <tr
        className={cn(
          "group hover:bg-surface-2/50 transition-colors cursor-pointer",
          expanded && "bg-surface-2/30"
        )}
        onClick={() => isFailed && setExpanded(!expanded)}
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
            result.status === "skipped" && "text-ink-tertiary"
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
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
