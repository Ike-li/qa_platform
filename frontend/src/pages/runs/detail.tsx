import { useParams, Link } from "react-router-dom";
import { 
  GitBranch, 
  Clock, 
  User,
  Terminal,
  FileText,
  Package,
  ChevronDown,
  ChevronRight,
  Download,
  ExternalLink,
  RotateCcw,
  Ban
} from "lucide-react";
import * as React from "react";
import { useRun, useRunResults, useRunArtifacts, useCancelRun } from "../../hooks/use-runs";
import type { TestResult } from "../../types/api";
import { RunStatusBadge } from "../../components/run-status-badge";
import { DurationDisplay } from "../../components/duration-display";
import { RelativeTime } from "../../components/relative-time";
import { LogViewer } from "../../components/runs/log-viewer";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Button } from "../../components/ui/button";
import { 
  AlertDialog, 
  AlertDialogAction, 
  AlertDialogCancel, 
  AlertDialogContent, 
  AlertDialogDescription, 
  AlertDialogFooter, 
  AlertDialogHeader, 
  AlertDialogTitle, 
  AlertDialogTrigger 
} from "../../components/ui/alert-dialog";
import { toast } from "sonner";
import { cn } from "../../lib/utils";

import { usePageTitle } from "../../hooks/use-page-title";

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: run, isLoading: isRunLoading } = useRun(id!);
  const { data: results, isLoading: isResultsLoading } = useRunResults(id!, { per_page: 50 });
  const { data: artifacts, isLoading: isArtifactsLoading } = useRunArtifacts(id!);
  
  const { mutateAsync: cancelRun, isPending: isCancelling } = useCancelRun(id!);

  usePageTitle(run ? `Run ${run.pipeline_name}` : "Run Details");

  const onCancelRun = async () => {
    try {
      await cancelRun(undefined);
      toast.success("Cancel request sent");
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || "Failed to cancel run");
    }
  };

  if (isRunLoading) {
    return <div className="animate-pulse space-y-6">
      <div className="h-12 w-full rounded bg-surface-1" />
      <div className="h-64 w-full rounded bg-surface-1" />
    </div>;
  }

  if (!run) return <div>Run not found</div>;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-6 rounded-xl border border-hairline bg-surface-1 p-6 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">Status</span>
            <RunStatusBadge status={run.status} className="text-sm px-3 py-1" />
          </div>
          
          <div className="flex flex-col gap-1">
            <h1 className="text-xl font-semibold text-ink">{run.pipeline_name}</h1>
            <div className="flex items-center gap-3 text-sm text-ink-muted">
              <Link to={`/projects/${run.project_id}`} className="hover:text-primary transition-colors flex items-center gap-1">
                Project Detail <ExternalLink className="h-3 w-3" />
              </Link>
              <span>•</span>
              <div className="flex items-center gap-1">
                <GitBranch className="h-3.5 w-3.5" />
                <span>{run.branch}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-8 border-t border-hairline pt-4 md:border-0 md:pt-0">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-ink-tertiary">Triggered By</span>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <User className="h-4 w-4 text-ink-subtle" />
              <span>{run.triggered_by}</span>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-ink-tertiary">Duration</span>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <Clock className="h-4 w-4 text-ink-subtle" />
              <DurationDisplay seconds={run.duration_seconds} />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-ink-tertiary">Created</span>
            <div className="text-sm font-medium">
              <RelativeTime date={run.created_at} />
            </div>
          </div>
        </div>

        <div className="flex gap-2">
          {run.status === "running" || run.status === "queued" || run.status === "preparing" || run.status === "collecting" ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm" className="text-status-failed border-status-failed/20 hover:bg-status-failed/5">
                  <Ban className="mr-2 h-4 w-4" /> Cancel
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Cancel Run?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Are you sure you want to cancel this execution? This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep Running</AlertDialogCancel>
                  <AlertDialogAction onClick={onCancelRun} className="bg-status-failed hover:bg-status-failed/90" disabled={isCancelling}>
                    {isCancelling ? "Cancelling..." : "Yes, Cancel"}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : (
            <Button variant="outline" size="sm">
              <RotateCcw className="mr-2 h-4 w-4" /> Re-run
            </Button>
          )}
        </div>
      </div>

      {/* Main Content Tabs */}
      <Tabs defaultValue="results" className="w-full">
        <TabsList>
          <TabsTrigger value="logs">
            <Terminal className="mr-2 h-4 w-4" /> Logs
          </TabsTrigger>
          <TabsTrigger value="results">
            <FileText className="mr-2 h-4 w-4" /> Test Results
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            <Package className="mr-2 h-4 w-4" /> Artifacts
          </TabsTrigger>
        </TabsList>

        <TabsContent value="logs" className="mt-4">
          <LogViewer runId={id!} />
        </TabsContent>

        <TabsContent value="results" className="mt-4 space-y-4">
          {/* Summary Bar */}
          <div className="grid grid-cols-4 gap-4">
            <SummaryCard label="Total" value={run.total_tests} color="muted" />
            <SummaryCard label="Passed" value={run.passed_tests} color="passed" />
            <SummaryCard label="Failed" value={run.failed_tests} color="failed" />
            <SummaryCard label="Skipped" value={run.skipped_tests} color="tertiary" />
          </div>

          <div className="rounded-xl border border-hairline bg-surface-1 overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-hairline bg-surface-2/50 text-ink-muted">
                  <th className="w-10 px-4 py-3"></th>
                  <th className="px-4 py-3 font-medium">Test Case</th>
                  <th className="px-4 py-3 font-medium">Suite</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {isResultsLoading ? (
                  [1, 2, 3].map(i => <tr key={i} className="animate-pulse"><td colSpan={5} className="p-4"><div className="h-4 w-full bg-surface-2 rounded" /></td></tr>)
                ) : results?.data.length === 0 ? (
                  <tr><td colSpan={5} className="p-12 text-center text-ink-tertiary">No test results reported yet.</td></tr>
                ) : (
                  results?.data.map(result => (
                    <TestResultRow key={result.id} result={result} />
                  ))
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="artifacts" className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {isArtifactsLoading ? (
              [1, 2].map(i => <div key={i} className="h-24 animate-pulse rounded-lg border border-hairline bg-surface-1" />)
            ) : artifacts?.length === 0 ? (
              <div className="col-span-full rounded-xl border border-hairline bg-surface-1 p-12 text-center text-sm text-ink-tertiary">
                No artifacts generated for this run.
              </div>
            ) : (
              artifacts?.map(artifact => (
                <div key={artifact.id} className="group flex items-center justify-between rounded-lg border border-hairline bg-surface-1 p-4 transition-colors hover:border-hairline-strong">
                  <div className="flex items-center gap-3">
                    <div className="rounded-md bg-surface-2 p-2 text-ink-subtle">
                      <Package className="h-5 w-5" />
                    </div>
                    <div>
                      <h4 className="font-medium text-ink text-sm">{artifact.name}</h4>
                      <p className="text-xs text-ink-muted">{(artifact.size_bytes / 1024 / 1024).toFixed(2)} MB • {artifact.type}</p>
                    </div>
                  </div>
                  <Button variant="ghost" size="icon" className="text-ink-subtle hover:text-primary">
                    <Download className="h-4 w-4" />
                  </Button>
                </div>
              ))
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SummaryCard({ label, value, color }: { label: string; value: number; color: "passed" | "failed" | "muted" | "tertiary" }) {
  const colors = {
    passed: "text-status-passed border-status-passed/20 bg-status-passed/5",
    failed: "text-status-failed border-status-failed/20 bg-status-failed/5",
    muted: "text-ink border-hairline bg-surface-1",
    tertiary: "text-ink-tertiary border-hairline bg-surface-1",
  };
  
  return (
    <div className={cn("rounded-lg border p-4 text-center", colors[color])}>
      <span className="text-xs font-medium uppercase tracking-wider opacity-80">{label}</span>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function TestResultRow({ result }: { result: TestResult }) {
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
            expanded ? <ChevronDown className="h-4 w-4 text-ink-tertiary" /> : <ChevronRight className="h-4 w-4 text-ink-tertiary" />
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
            {result.status === "passed" ? <RotateCcw className="h-3 w-3 hidden" /> : null}
            {result.status}
          </span>
        </td>
        <td className="px-4 py-3 text-ink-tertiary">{result.duration_ms}ms</td>
      </tr>
      {expanded && isFailed && (
        <tr>
          <td colSpan={5} className="bg-surface-2/20 px-8 py-4">
            <div className="rounded-md border border-status-failed/20 bg-status-failed/5 p-4 space-y-3">
              <p className="font-semibold text-status-failed text-sm">{result.error_message || "Unknown error"}</p>
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
