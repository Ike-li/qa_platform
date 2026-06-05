import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import {
  GitBranch,
  Settings as SettingsIcon,
  Activity,
  Layers,
  Globe,
  Play,
  Plus,
  ArrowRight,
  TrendingUp,
  Bell,
} from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
  useProject,
  useProjectEnvironments,
  useProjectPipelines,
  useUpdateProject,
  useDeleteProject
} from "../../hooks/use-projects";
import { useRuns } from "../../hooks/use-runs";
import { useNotificationRules } from "../../hooks/use-notifications";
import type { Pipeline } from "../../types/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
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
import { PipelineModal } from "../../components/projects/pipeline-modal";
import { TriggerRunModal } from "../../components/runs/trigger-run-modal";
import { AnalyticsPanel } from "../../components/projects/analytics-panel";
import { EnvironmentEditor } from "../../components/projects/environment-editor";
import { NotificationRulesPanel } from "../../components/projects/notification-rules-panel";
import { SetupChecklist } from "../../components/projects/setup-checklist";
import { SilentWindowsEditor } from "../../components/projects/silent-windows-editor";
import {
  normalizeSilentWindows,
  toSilentWindowFormValues,
  type SilentWindowFormValue,
} from "../../components/projects/silent-windows-utils";
import { cn } from "../../lib/utils";
import { usePageTitle } from "../../hooks/use-page-title";
import { RunStatusBadge } from "../../components/run-status-badge";
import { RelativeTime } from "../../components/relative-time";
import { createProjectSchema, type ProjectFormValues } from "./detail-form";

type SilentWindowState = {
  projectKey: string;
  windows: SilentWindowFormValue[];
};

type SilentWindowErrorState = {
  projectKey: string;
  message: string;
};

export default function ProjectDetail() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectId = id ?? "";
  const routeTab = searchParams.get("tab");
  const initialTab = ["runs", "pipelines", "environments", "analytics", "notifications", "settings"].includes(routeTab ?? "")
    ? routeTab!
    : "runs";
  const activeTab = initialTab;
  const [isPipelineModalOpen, setIsPipelineModalOpen] = React.useState(false);
  const [selectedPipeline, setSelectedPipeline] = React.useState<Pipeline | undefined>(undefined);
  const [isTriggerModalOpen, setIsTriggerModalOpen] = React.useState(false);
  const [silentWindowState, setSilentWindowState] = React.useState<SilentWindowState | null>(null);
  const [silentWindowErrorState, setSilentWindowErrorState] = React.useState<SilentWindowErrorState | null>(null);

  const { data: project, isLoading: isProjectLoading } = useProject(projectId);
  const { data: pipelines, isLoading: isPipelinesLoading } = useProjectPipelines(projectId);
  const { data: environments, isLoading: isEnvironmentsLoading } = useProjectEnvironments(projectId);
  const { data: notificationRules, isLoading: isNotificationsLoading } = useNotificationRules(projectId);
  const { data: recentRuns, isLoading: isRunsLoading } = useRuns({
    project_id: projectId,
    per_page: 5,
    sort: "-created_at",
    enabled: Boolean(projectId),
  });
  const runs = recentRuns?.data ?? [];
  const projectKey = project ? `${project.id}:${project.updated_at}` : "";
  const projectSilentWindows = React.useMemo(
    () => toSilentWindowFormValues(project?.silent_windows),
    [project?.silent_windows]
  );
  const silentWindows = silentWindowState?.projectKey === projectKey
    ? silentWindowState.windows
    : projectSilentWindows;
  const silentWindowError = silentWindowErrorState?.projectKey === projectKey
    ? silentWindowErrorState.message
    : null;

  const setCurrentSilentWindows = (windows: SilentWindowFormValue[]) => {
    setSilentWindowState({ projectKey, windows });
  };

  const setCurrentSilentWindowError = (message: string | null) => {
    setSilentWindowErrorState(message ? { projectKey, message } : null);
  };

  usePageTitle(project ? project.name : t("projects.detailTitle"));

  const selectTab = (value: string) => {
    const nextParams = new URLSearchParams(searchParams);
    if (value === "runs") {
      nextParams.delete("tab");
    } else {
      nextParams.set("tab", value);
    }
    setSearchParams(nextParams, { replace: true });
  };

  const openNewPipeline = () => {
    setSelectedPipeline(undefined);
    setIsPipelineModalOpen(true);
  };

  const openEditPipeline = (pipeline: Pipeline) => {
    setSelectedPipeline(pipeline);
    setIsPipelineModalOpen(true);
  };

  const { mutateAsync: updateProject, isPending: isUpdating } = useUpdateProject(projectId);
  const { mutateAsync: deleteProject } = useDeleteProject(projectId);

  const projectSchema = createProjectSchema();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ProjectFormValues>({
    resolver: zodResolver(projectSchema),
  });

  React.useEffect(() => {
    if (project) {
      reset({
        name: project.name,
        description: project.description || "",
        git_url: project.git_url,
        default_branch: project.default_branch,
        root_path: project.root_path,
      });
    }
  }, [project, reset]);

  const onUpdateSubmit = async (data: ProjectFormValues) => {
    try {
      await updateProject(data);
      toast.success(t('projects.toast.updated'));
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('projects.toast.updateFailed'));
    }
  };

  const onDeleteProject = async () => {
    try {
      await deleteProject();
      toast.success(t('projects.toast.deleted'));
      navigate("/projects");
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('projects.toast.deleteFailed'));
    }
  };

  const onArchiveProject = async () => {
    try {
      await updateProject({ status: "archived" });
      toast.success(t('projects.toast.archived'));
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('projects.toast.archiveFailed'));
    }
  };

  const addSilentWindow = () => {
    if (silentWindows.length >= 20) {
      setCurrentSilentWindowError(t('projects.silentWindows.limit'));
      return;
    }
    setCurrentSilentWindows([...silentWindows, { start_at: "", end_at: "", reason: "" }]);
    setCurrentSilentWindowError(null);
  };

  const updateSilentWindow = (
    index: number,
    key: keyof SilentWindowFormValue,
    value: string,
  ) => {
    setCurrentSilentWindows(
      silentWindows.map((window, current) => (
        current === index ? { ...window, [key]: value } : window
      ))
    );
    setCurrentSilentWindowError(null);
  };

  const removeSilentWindow = (index: number) => {
    setCurrentSilentWindows(silentWindows.filter((_, current) => current !== index));
    setCurrentSilentWindowError(null);
  };

  const onSaveSilentWindows = async () => {
    try {
      await updateProject({ silent_windows: normalizeSilentWindows(silentWindows) });
      toast.success(t('projects.silentWindows.saved'));
      setCurrentSilentWindowError(null);
    } catch (error: unknown) {
      if (error instanceof Error && error.message === "required") {
        setCurrentSilentWindowError(t('projects.silentWindows.required'));
        return;
      }
      if (error instanceof Error && error.message === "range") {
        setCurrentSilentWindowError(t('projects.silentWindows.range'));
        return;
      }
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('projects.silentWindows.saveFailed'));
    }
  };

  if (isProjectLoading) {
    return <div className="animate-pulse space-y-6">
      <div className="h-8 w-64 rounded bg-surface-1" />
      <div className="h-4 w-full rounded bg-surface-1" />
      <div className="h-64 w-full rounded bg-surface-1" />
    </div>;
  }

  if (!project) return <div>{t('projects.notFound')}</div>;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight text-ink">{project.name}</h1>
            <span className={cn(
              "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium capitalize",
              project.status === "active" ? "border-status-passed/20 bg-status-passed/10 text-status-passed" : "border-ink-tertiary/20 bg-ink-tertiary/10 text-ink-tertiary"
            )}>
              {t('projectStatus.' + project.status)}
            </span>
          </div>
          <p className="max-w-2xl text-ink-subtle">{project.description || t('projects.noDescription')}</p>
          <div className="flex flex-wrap items-center gap-4 pt-2 text-sm text-ink-muted">
            <div className="flex items-center gap-1.5">
              <GitBranch className="h-4 w-4" />
              <span>{project.default_branch}</span>
            </div>
            <div className="flex items-center gap-1.5 font-mono text-xs opacity-80">
              <Globe className="h-4 w-4" />
              <span>{project.git_url}</span>
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setIsTriggerModalOpen(true)}>
            <Play className="mr-2 h-4 w-4" /> {t('projects.triggerRun')}
          </Button>
        </div>
      </div>

      <TriggerRunModal
        projectId={projectId}
        open={isTriggerModalOpen}
        onOpenChange={setIsTriggerModalOpen}
        onCreatePipeline={openNewPipeline}
      />

      <SetupChecklist
        project={project}
        pipelines={pipelines}
        environments={environments}
        runs={runs}
        notificationRules={notificationRules}
        isLoading={isPipelinesLoading || isEnvironmentsLoading || isRunsLoading || isNotificationsLoading}
        onOpenSettings={() => selectTab("settings")}
        onOpenPipelines={() => {
          selectTab("pipelines");
          if ((pipelines?.length ?? 0) === 0) openNewPipeline();
        }}
        onOpenEnvironments={() => selectTab("environments")}
        onOpenNotifications={() => selectTab("notifications")}
        onTriggerRun={() => setIsTriggerModalOpen(true)}
      />

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={selectTab} className="w-full">
        <TabsList className="mb-6">
          <TabsTrigger value="runs">
            <Activity className="mr-2 h-4 w-4" /> {t('projects.tabs.runs')}
          </TabsTrigger>
          <TabsTrigger value="pipelines">
            <Layers className="mr-2 h-4 w-4" /> {t('projects.tabs.pipelines')}
          </TabsTrigger>
          <TabsTrigger value="environments">
            <Globe className="mr-2 h-4 w-4" /> {t('projects.tabs.environments')}
          </TabsTrigger>
          <TabsTrigger value="analytics">
            <TrendingUp className="mr-2 h-4 w-4" /> {t('projects.tabs.analytics')}
          </TabsTrigger>
          <TabsTrigger value="notifications">
            <Bell className="mr-2 h-4 w-4" /> {t('projects.tabs.notifications')}
          </TabsTrigger>
          <TabsTrigger value="settings">
            <SettingsIcon className="mr-2 h-4 w-4" /> {t('projects.tabs.settings')}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="runs" className="space-y-4">
          <div className="rounded-xl border border-hairline bg-surface-1">
            <div className="flex flex-col gap-3 border-b border-hairline p-4 md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-base font-semibold text-ink">{t("projects.recentRuns.title")}</h2>
                <p className="text-sm text-ink-muted">{t("projects.recentRuns.description")}</p>
              </div>
              <Button variant="outline" onClick={() => setIsTriggerModalOpen(true)}>
                <Play className="mr-2 h-4 w-4" />
                {t("projects.triggerRun")}
              </Button>
            </div>
            <div className="divide-y divide-hairline">
              {isRunsLoading ? (
                [1, 2, 3].map((item) => (
                  <div key={item} className="h-20 animate-pulse bg-surface-1" />
                ))
              ) : runs.length === 0 ? (
                <div className="p-12 text-center">
                  <p className="text-sm text-ink-tertiary">{t('projects.noRuns')}</p>
                  <Button variant="outline" className="mt-4" onClick={() => setIsTriggerModalOpen(true)}>
                    {t('projects.triggerFirstRun')}
                  </Button>
                </div>
              ) : (
                runs.map((run) => (
                  <button
                    key={run.id}
                    type="button"
                    className="flex w-full flex-col gap-3 p-4 text-left transition-colors hover:bg-canvas md:flex-row md:items-center md:justify-between"
                    onClick={() => navigate(`/runs/${run.id}`)}
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <RunStatusBadge status={run.status} />
                        <span className="truncate font-medium text-ink">{run.pipeline_name}</span>
                        <span className="font-mono text-xs text-ink-tertiary">{run.git_sha?.slice(0, 8) ?? "-"}</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-xs text-ink-muted">
                        <span className="inline-flex items-center gap-1">
                          <GitBranch className="h-3.5 w-3.5" />
                          {run.branch}
                        </span>
                        <span>{t("runs.testsSummary", {
                          total: run.total_tests,
                          passed: run.passed_tests,
                          failed: run.failed_tests,
                        })}</span>
                      </div>
                    </div>
                    <div className="flex items-center justify-between gap-3 text-sm text-ink-muted md:justify-end">
                      <RelativeTime date={run.created_at} />
                      <ArrowRight className="h-4 w-4" />
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="pipelines" className="space-y-4">
          <div className="flex justify-end">
            <Button size="sm" onClick={openNewPipeline}>
              <Plus className="mr-2 h-4 w-4" /> {t('projects.newPipeline')}
            </Button>
          </div>
          <PipelineModal
            projectId={projectId}
            pipeline={selectedPipeline}
            open={isPipelineModalOpen}
            onOpenChange={setIsPipelineModalOpen}
          />
          <div className="grid gap-4">
            {isPipelinesLoading ? (
              [1, 2].map(i => <div key={i} className="h-20 animate-pulse rounded-lg border border-hairline bg-surface-1" />)
            ) : pipelines?.length === 0 ? (
              <div className="rounded-xl border border-hairline bg-surface-1 p-12 text-center text-sm text-ink-tertiary">
                {t('projects.noPipelines')}
              </div>
            ) : (
              pipelines?.map(pipeline => (
                <div key={pipeline.id} className="flex items-center justify-between rounded-lg border border-hairline bg-surface-1 p-4 transition-colors hover:border-hairline-strong">
                  <div className="flex items-center gap-4">
                    <div className={cn(
                      "flex h-10 w-10 items-center justify-center rounded-md border",
                      pipeline.enabled ? "bg-status-passed/5 border-status-passed/20 text-status-passed" : "bg-ink-tertiary/5 border-ink-tertiary/20 text-ink-tertiary"
                    )}>
                      <Layers className="h-5 w-5" />
                    </div>
                    <div>
                      <h4 className="font-medium text-ink">{pipeline.name}</h4>
                      <div className="flex items-center gap-3 text-xs text-ink-muted">
                        <span>{pipeline.stages[0]?.plugin ?? pipeline.trigger_config.type}</span>
                        <span>•</span>
                        <span>{t('pipelines.minuteTimeout', { minutes: pipeline.timeout_seconds / 60 })}</span>
                        {!pipeline.enabled && <span className="text-status-failed">{t('pipelines.disabled')}</span>}
                      </div>
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => openEditPipeline(pipeline)}>
                    {t('common.edit')} <ArrowRight className="ml-2 h-3 w-3" />
                  </Button>
                </div>
              ))
            )}
          </div>
        </TabsContent>

        <TabsContent value="environments" className="space-y-4">
          <EnvironmentEditor projectId={projectId} />
        </TabsContent>

        <TabsContent value="analytics">
          <AnalyticsPanel
            projectId={projectId}
            defaultBranch={project.default_branch}
            initialSuite={searchParams.get("suite") ?? undefined}
            initialTest={searchParams.get("test") ?? undefined}
          />
        </TabsContent>

        <TabsContent value="notifications">
          <NotificationRulesPanel projectId={projectId} />
        </TabsContent>

        <TabsContent value="settings" className="space-y-6 max-w-2xl">
          <form onSubmit={handleSubmit(onUpdateSubmit)} className="rounded-xl border border-hairline bg-surface-1 p-6 space-y-4">
            <h3 className="text-lg font-medium">{t('projects.settings.title')}</h3>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">{t('projects.settings.name')}</Label>
                <Input id="name" {...register("name")} />
                {errors.name && <p className="text-xs text-status-failed">{errors.name.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">{t('projects.settings.description')}</Label>
                <Textarea id="description" {...register("description")} rows={3} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="git_url">{t('projects.settings.gitUrl')}</Label>
                <Input id="git_url" {...register("git_url")} />
                {errors.git_url && <p className="text-xs text-status-failed">{errors.git_url.message}</p>}
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="default_branch">{t('projects.settings.defaultBranch')}</Label>
                  <Input id="default_branch" {...register("default_branch")} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="root_path">{t('projects.settings.rootPath')}</Label>
                  <Input id="root_path" {...register("root_path")} />
                </div>
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <Button type="submit" disabled={isUpdating}>
                {isUpdating ? t('projects.settings.saving') : t('projects.settings.saveChanges')}
              </Button>
            </div>
          </form>

          <SilentWindowsEditor
            windows={silentWindows}
            error={silentWindowError}
            isSaving={isUpdating}
            onAdd={addSilentWindow}
            onChange={updateSilentWindow}
            onRemove={removeSilentWindow}
            onSave={onSaveSilentWindows}
          />

          <div className="rounded-xl border border-status-failed/20 bg-status-failed/5 p-6 space-y-4">
            <h3 className="text-lg font-medium text-status-failed">{t('projects.danger.title')}</h3>
            <p className="text-sm text-ink-muted">{t('projects.danger.description')}</p>
            <div className="flex flex-wrap gap-3">
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="outline" className="text-ink hover:text-ink">{t('projects.danger.archiveProject')}</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>{t('projects.danger.archiveConfirmTitle')}</AlertDialogTitle>
                    <AlertDialogDescription>
                      {t('projects.danger.archiveConfirmDescription')}
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                    <AlertDialogAction onClick={onArchiveProject}>{t('projects.danger.archive')}</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="destructive">{t('projects.danger.deleteProject')}</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>{t('projects.danger.deleteConfirmTitle')}</AlertDialogTitle>
                    <AlertDialogDescription>
                      {t('projects.danger.deleteConfirmDescription')}
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                    <AlertDialogAction onClick={onDeleteProject} className="bg-status-failed hover:bg-status-failed/90">
                      {t('projects.danger.deleteProject')}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
