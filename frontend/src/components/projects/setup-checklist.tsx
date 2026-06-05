import { CheckCircle2, Circle } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  Environment,
  NotificationRule,
  Pipeline,
  Project,
  Run,
} from "../../types/api";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";

type SetupChecklistProps = {
  project: Project;
  pipelines: Pipeline[] | undefined;
  environments: Environment[] | undefined;
  runs: Run[] | undefined;
  notificationRules: NotificationRule[] | undefined;
  isLoading: boolean;
  onOpenSettings: () => void;
  onOpenPipelines: () => void;
  onOpenEnvironments: () => void;
  onOpenNotifications: () => void;
  onTriggerRun: () => void;
};

export function SetupChecklist({
  project,
  pipelines,
  environments,
  runs,
  notificationRules,
  isLoading,
  onOpenSettings,
  onOpenPipelines,
  onOpenEnvironments,
  onOpenNotifications,
  onTriggerRun,
}: SetupChecklistProps) {
  const { t } = useTranslation();
  const pipelineCount = pipelines?.length ?? 0;
  const environmentCount = environments?.length ?? 0;
  const runCount = runs?.length ?? 0;
  const notificationCount =
    notificationRules?.filter((rule) => rule.enabled).length ?? 0;
  const credentialReady =
    project.git_auth_method === "none" || Boolean(project.credential_id);

  const steps = [
    {
      key: "git",
      title: t("projects.setup.git.title"),
      detail: project.git_url || t("projects.setup.git.pending"),
      complete: Boolean(project.git_url && project.default_branch),
      action: onOpenSettings,
    },
    {
      key: "credential",
      title: t("projects.setup.credential.title"),
      detail: credentialReady
        ? t("projects.setup.credential.ready")
        : t("projects.setup.credential.pending"),
      complete: credentialReady,
      action: onOpenSettings,
    },
    {
      key: "pipeline",
      title: t("projects.setup.pipeline.title"),
      detail:
        pipelineCount > 0
          ? t("projects.setup.pipeline.ready", { count: pipelineCount })
          : t("projects.setup.pipeline.pending"),
      complete: pipelineCount > 0,
      action: onOpenPipelines,
    },
    {
      key: "environment",
      title: t("projects.setup.environment.title"),
      detail:
        project.default_env_id || environmentCount > 0
          ? t("projects.setup.environment.ready", { count: environmentCount })
          : t("projects.setup.environment.pending"),
      complete: Boolean(project.default_env_id || environmentCount > 0),
      action: onOpenEnvironments,
    },
    {
      key: "firstRun",
      title: t("projects.setup.firstRun.title"),
      detail:
        runCount > 0
          ? t("projects.setup.firstRun.ready", { count: runCount })
          : t("projects.setup.firstRun.pending"),
      complete: runCount > 0,
      action: onTriggerRun,
    },
    {
      key: "notifications",
      title: t("projects.setup.notifications.title"),
      detail:
        notificationCount > 0
          ? t("projects.setup.notifications.ready", { count: notificationCount })
          : t("projects.setup.notifications.pending"),
      complete: notificationCount > 0,
      optional: true,
      action: onOpenNotifications,
    },
  ];

  const requiredSteps = steps.filter((step) => !step.optional);
  const completedRequired = requiredSteps.filter((step) => step.complete).length;

  return (
    <section className="rounded-xl border border-hairline bg-surface-1 p-5">
      <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-base font-semibold text-ink">
            {t("projects.setup.title")}
          </h2>
          <p className="text-sm text-ink-muted">
            {t("projects.setup.description")}
          </p>
        </div>
        <div className="text-sm font-medium text-ink">
          {t("projects.setup.progress", {
            completed: completedRequired,
            total: requiredSteps.length,
          })}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {steps.map((step) => {
          const StepIcon = step.complete ? CheckCircle2 : Circle;
          return (
            <div
              key={step.key}
              className={cn(
                "flex min-h-[104px] flex-col justify-between rounded-lg border p-3",
                step.complete
                  ? "border-status-passed/25 bg-status-passed/5"
                  : "border-hairline bg-canvas"
              )}
            >
              <div className="flex items-start gap-3">
                <StepIcon
                  className={cn(
                    "mt-0.5 h-4 w-4 shrink-0",
                    step.complete ? "text-status-passed" : "text-ink-tertiary"
                  )}
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink">
                      {step.title}
                    </p>
                    {step.optional && (
                      <span className="rounded-full border border-hairline px-2 py-0.5 text-[11px] text-ink-muted">
                        {t("projects.setup.optional")}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 break-words text-xs text-ink-muted">
                    {step.detail}
                  </p>
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="text-xs text-ink-tertiary">
                  {isLoading
                    ? t("common.loading")
                    : step.complete
                      ? t("projects.setup.done")
                      : t("projects.setup.todo")}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={step.action}
                >
                  {step.complete
                    ? t("projects.setup.review")
                    : t("projects.setup.open")}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
