import { useParams, Link, useNavigate } from "react-router-dom";
import {
  Clock,
  User,
  Terminal,
  FileText,
  Package,
  Download,
  ExternalLink,
  RotateCcw,
  Ban,
  Eye,
  TrendingUp
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  useRun,
  useRunResults,
  useRunArtifacts,
  useRunAllureReportArtifact,
  useCancelRun,
  useTriggerRun,
  useArtifactPreviewUrl,
} from "../../hooks/use-runs";
import { RunStatusBadge } from "../../components/run-status-badge";
import { BranchBadge } from "../../components/branch-badge";
import { DurationDisplay } from "../../components/duration-display";
import { RelativeTime } from "../../components/relative-time";
import { LogViewer } from "../../components/runs/log-viewer";
import { FailureTriagePanel } from "../../components/runs/failure-triage-panel";
import { RetryFailedButton } from "../../components/runs/retry-failed-button";
import { TestResultsTable } from "../../components/test-results-table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Button } from "../../components/ui/button";
import type { Artifact, TestResult } from "../../types/api";
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
import { cn, isSafeArtifactUrl } from "../../lib/utils";

import { usePageTitle } from "../../hooks/use-page-title";
import { getArtifactDownloadUrl, getArtifactPreviewUrl } from "../../lib/api";
import { ArtifactPreview } from "../../components/runs/artifact-preview";
import { ShareReportDialog } from "../../components/runs/share-report-dialog";
import { useState } from "react";

type PreviewState = {
  url: string;
  title: string;
  iframeTitle: string;
};

function isPreviewableArtifact(artifact: Artifact): boolean {
  const name = artifact.name.toLowerCase();
  const mimeType = artifact.mime_type.toLowerCase().split(";", 1)[0].trim();

  return (
    artifact.type === "allure-report" ||
    artifact.type === "html" ||
    mimeType === "text/html" ||
    name.endsWith(".html") ||
    name.endsWith(".htm")
  );
}

function getArtifactPreviewTitle(artifact: Artifact): string {
  return artifact.type === "allure-report" ? "Allure Report" : artifact.name;
}

function getArtifactPreviewFrameTitle(artifact: Artifact): string {
  return artifact.type === "allure-report"
    ? "Allure Report Preview"
    : `${artifact.name} Preview`;
}

function testResultSortPriority(result: TestResult): number {
  if (result.status === "failed") return 0;
  if (result.status === "error") return 1;
  if (result.status === "passed") return 2;
  return 3;
}

export default function RunDetail() {
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [activeTab, setActiveTab] = useState("results");
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { data: run, isLoading: isRunLoading } = useRun(id!);
  const { data: results, isLoading: isResultsLoading } = useRunResults(id!, { per_page: 50 });
  const { data: artifacts, isLoading: isArtifactsLoading } = useRunArtifacts(id!);
  const { data: allureReportArtifact } = useRunAllureReportArtifact(id!);

  const { mutateAsync: cancelRun, isPending: isCancelling } = useCancelRun(id!);
  const { mutateAsync: triggerRun, isPending: isReRunning } = useTriggerRun();

  // Allure report preview — auto-fetched via TanStack Query when the
  // artifact is available.  Replaces the previous useEffect +
  // setAllurePreview pattern.
  const {
    data: allureReportUrl,
    isLoading: isAllureReportLoading,
    isError: allureReportPreviewFailed,
  } = useArtifactPreviewUrl(allureReportArtifact?.id);

  const hasAllureReport = Boolean(allureReportArtifact);

  const orderedResults = [...(results?.data ?? [])].sort((a, b) => (
    testResultSortPriority(a) - testResultSortPriority(b)
  ));
  const failedResults = orderedResults.filter((result) => (
    result.status === "failed" || result.status === "error"
  ));

  usePageTitle(run ? `Run ${run.pipeline_name}` : t('runs.notFound'));

  const onCancelRun = async () => {
    try {
      await cancelRun(undefined);
      toast.success(t('runs.toast.cancelSent'));
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('runs.toast.cancelFailed'));
    }
  };

  const onReRun = async () => {
    if (!run) return;

    try {
      const nextRun = await triggerRun({
        pipeline_id: run.pipeline_id,
        branch: run.branch === "-" ? undefined : run.branch,
        git_sha: run.git_sha ?? undefined,
        environment_id: run.environment_id,
        priority: run.priority,
      });
      toast.success(t('runs.toast.reRunStarted'));
      void navigate(`/runs/${nextRun.id}`);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('runs.toast.reRunFailed'));
    }
  };

  if (isRunLoading) {
    return <div className="animate-pulse space-y-6">
      <div className="h-12 w-full rounded bg-surface-1" />
      <div className="h-64 w-full rounded bg-surface-1" />
    </div>;
  }

  if (!run) return <div>{t('runs.notFound')}</div>;
  const archivedLogsEnabled = run.is_terminal;
  const shouldShowTriage = run.status === "failed" || run.failed_tests > 0 || Boolean(run.error_message);
  const firstFailure = failedResults[0];
  const failureMessage = firstFailure?.error_message || run.error_message || t("runs.triage.noFailureMessage");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-6 rounded-xl border border-hairline bg-surface-1 p-6 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">{t('runs.detail.status')}</span>
            <RunStatusBadge status={run.status} className="text-sm px-3 py-1" />
          </div>

          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold text-ink">{run.pipeline_name}</h1>
              <span className={cn(
                "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium border capitalize",
                run.trigger_type === "import"
                  ? "bg-status-queued/10 text-status-queued border-status-queued/20"
                  : "bg-surface-2 text-ink-muted border-hairline"
              )}>
                {t(`runs.triggerType.${run.trigger_type}`, { defaultValue: run.trigger_type })}
              </span>
            </div>
            <div className="flex items-center gap-3 text-sm text-ink-muted">
              <Link to={`/projects/${run.project_id}`} className="hover:text-primary transition-colors flex items-center gap-1">
                {t('runs.detail.projectDetail')} <ExternalLink className="h-3 w-3" />
              </Link>
              <span>•</span>
              <Link
                to={`/projects/${run.project_id}?tab=analytics&git_ref=${encodeURIComponent(run.git_sha || run.branch)}&baseline_git_ref=${encodeURIComponent(run.branch)}`}
                className="hover:text-primary transition-colors flex items-center gap-1"
              >
                {t('runs.detail.releaseVerdict')} <TrendingUp className="h-3.5 w-3.5" />
              </Link>
              <span>•</span>
              <BranchBadge branch={run.branch} />
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-8 border-t border-hairline pt-4 md:border-0 md:pt-0">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-ink-tertiary">{t('runs.detail.triggeredBy')}</span>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <User className="h-4 w-4 text-ink-subtle" />
              <span>{run.triggered_by}</span>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-ink-tertiary">{t('runs.detail.duration')}</span>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <Clock className="h-4 w-4 text-ink-subtle" />
              <DurationDisplay seconds={run.duration_seconds} />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-ink-tertiary">{t('runs.detail.created')}</span>
            <div className="text-sm font-medium">
              <RelativeTime date={run.created_at} />
            </div>
          </div>
        </div>

        <div className="flex gap-2">
          {/* Share Report Button (only show when Allure report exists) */}
          {hasAllureReport && run.is_terminal && (
            <ShareReportDialog runId={run.id} />
          )}

          {run.status === "running" || run.status === "queued" || run.status === "preparing" || run.status === "collecting" ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm" className="text-status-failed border-status-failed/20 hover:bg-status-failed/5">
                  <Ban className="mr-2 h-4 w-4" /> {t('runs.cancel')}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t('runs.cancelTitle')}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t('runs.cancelDescription')}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t('runs.keepRunning')}</AlertDialogCancel>
                  <AlertDialogAction onClick={onCancelRun} className="bg-status-failed hover:bg-status-failed/90" disabled={isCancelling}>
                    {isCancelling ? t('runs.cancelling') : t('runs.yesCancel')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : (
            <Button variant="outline" size="sm" onClick={onReRun} disabled={isReRunning}>
              <RotateCcw className="mr-2 h-4 w-4" /> {isReRunning ? t('runs.reRunning') : t('runs.reRun')}
            </Button>
          )}
        </div>
      </div>

      {shouldShowTriage && (
        <div className="space-y-4">
          <section className="rounded-xl border border-status-failed/20 bg-status-failed/5 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0 space-y-2">
                <h2 className="text-base font-semibold text-status-failed">{t("runs.summary.title")}</h2>
                <p className="line-clamp-3 break-words text-sm text-ink">
                  {failureMessage}
                </p>
                <div className="flex flex-wrap gap-3 text-xs text-ink-muted">
                  <span>{t("runs.summary.failedTests", { count: failedResults.length || run.failed_tests })}</span>
                  <span>{t("runs.summary.totalTests", { count: run.total_tests })}</span>
                  <span>{run.branch}</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => setActiveTab("results")}>
                  <FileText className="mr-2 h-4 w-4" />
                  {t("runs.summary.results")}
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={() => setActiveTab("logs")}>
                  <Terminal className="mr-2 h-4 w-4" />
                  {t("runs.summary.logs")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setActiveTab(hasAllureReport ? "report" : "artifacts")}
                >
                  <Package className="mr-2 h-4 w-4" />
                  {hasAllureReport ? t("runs.summary.report") : t("runs.summary.artifacts")}
                </Button>
                <RetryFailedButton runId={run.id} failedCount={failedResults.length || run.failed_tests} />
                <Button type="button" size="sm" onClick={onReRun} disabled={isReRunning}>
                  <RotateCcw className="mr-2 h-4 w-4" />
                  {isReRunning ? t("runs.reRunning") : t("runs.reRun")}
                </Button>
              </div>
            </div>
          </section>

          <FailureTriagePanel runId={run.id} />
        </div>
      )}

      {/* Main Content Tabs */}
      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="w-full"
      >
        <TabsList>
          <TabsTrigger value="logs">
            <Terminal className="mr-2 h-4 w-4" /> {t('runs.tabs.logs')}
          </TabsTrigger>
          {hasAllureReport && (
            <TabsTrigger value="report">
              <FileText className="mr-2 h-4 w-4" /> {t('runs.tabs.report')}
            </TabsTrigger>
          )}
          <TabsTrigger value="results">
            <FileText className="mr-2 h-4 w-4" /> {t('runs.tabs.results')}
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            <Package className="mr-2 h-4 w-4" /> {t('runs.tabs.artifacts')}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="logs" className="mt-4">
          <LogViewer runId={id!} archivedEnabled={archivedLogsEnabled} />
        </TabsContent>

        {hasAllureReport && (
          <TabsContent value="report" className="mt-4">
            <div className="h-[72vh] overflow-hidden rounded-lg border border-hairline bg-surface-1">
              {isAllureReportLoading || !allureReportUrl ? (
                <div className="flex h-full items-center justify-center text-sm text-ink-tertiary">
                  {allureReportPreviewFailed
                    ? t('runs.artifacts.previewFailed')
                    : t('runs.report.loading')}
                </div>
              ) : (
                <iframe
                  src={allureReportUrl}
                  title="Allure Report Preview"
                  className="h-full w-full border-0"
                  sandbox="allow-scripts"
                  referrerPolicy="no-referrer"
                />
              )}
            </div>
          </TabsContent>
        )}

        <TabsContent value="results" className="mt-4 space-y-4">
          {/* Summary Bar */}
          <div className="grid grid-cols-4 gap-4">
            <SummaryCard label={t('runs.results.total')} value={run.total_tests} color="muted" />
            <SummaryCard label={t('runs.results.passed')} value={run.passed_tests} color="passed" />
            <SummaryCard label={t('runs.results.failed')} value={run.failed_tests} color="failed" />
            <SummaryCard label={t('runs.results.skipped')} value={run.skipped_tests} color="tertiary" />
          </div>

          <TestResultsTable
            results={orderedResults}
            isLoading={isResultsLoading}
            projectId={run.project_id}
          />
        </TabsContent>

        <TabsContent value="artifacts" className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {isArtifactsLoading ? (
              [1, 2].map(i => <div key={i} className="h-24 animate-pulse rounded-lg border border-hairline bg-surface-1" />)
            ) : artifacts?.length === 0 ? (
              <div className="col-span-full rounded-xl border border-hairline bg-surface-1 p-12 text-center text-sm text-ink-tertiary">
                {t('runs.artifacts.noArtifacts')}
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
                  <div className="flex items-center gap-1">
                    {isPreviewableArtifact(artifact) && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-ink-subtle hover:text-primary"
                        aria-label={t('runs.artifacts.previewArtifact', { name: artifact.name })}
                        title={t('runs.artifacts.previewArtifact', { name: artifact.name })}
                        onClick={async () => {
                          try {
                            const url = await getArtifactPreviewUrl(artifact.id);
                            if (!isSafeArtifactUrl(url)) {
                              toast.error(t('runs.artifacts.previewFailed'));
                              return;
                            }
                            setPreview({
                              url,
                              title: getArtifactPreviewTitle(artifact),
                              iframeTitle: getArtifactPreviewFrameTitle(artifact),
                            });
                          } catch {
                            toast.error(t('runs.artifacts.previewFailed'));
                          }
                        }}
                      >
                        <Eye className="h-4 w-4" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-ink-subtle hover:text-primary"
                      aria-label={t('runs.artifacts.downloadArtifact', { name: artifact.name })}
                      title={t('runs.artifacts.downloadArtifact', { name: artifact.name })}
                      onClick={async () => {
                        try {
                          const url = await getArtifactDownloadUrl(artifact.id);
                          if (!isSafeArtifactUrl(url)) {
                            toast.error(t('runs.artifacts.downloadFailed'));
                            return;
                          }
                          window.open(url, "_blank", "noopener,noreferrer");
                        } catch {
                          toast.error(t('runs.artifacts.downloadFailed'));
                        }
                      }}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </TabsContent>
      </Tabs>
      {preview && (
        <ArtifactPreview
          url={preview.url}
          title={preview.title}
          iframeTitle={preview.iframeTitle}
          onClose={() => setPreview(null)}
        />
      )}
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
