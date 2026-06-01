import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTriggerRun } from "../../hooks/use-runs";
import {
  useProjectEnvironments,
  useProjectPipelines,
} from "../../hooks/use-projects";
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle, 
  DialogFooter,
  DialogDescription
} from "../../components/ui/dialog";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from "../../components/ui/select";

const DEFAULT_ENVIRONMENT = "__project_default__";

const triggerSchema = z.object({
  pipeline_id: z.string().min(1),
  branch: z.string().optional(),
  git_sha: z
    .string()
    .trim()
    .refine(
      (value) => !value || /^[0-9a-fA-F]{40}$/.test(value),
      "validation.gitShaInvalid",
    )
    .optional(),
  environment_id: z.string().optional(),
  priority: z.coerce.number().min(0).max(2).default(1),
});

type TriggerFormInput = z.input<typeof triggerSchema>;
type TriggerFormValues = z.output<typeof triggerSchema>;

export function TriggerRunModal({ 
  projectId, 
  open, 
  onOpenChange,
  defaultPipelineId
}: { 
  projectId: string; 
  open: boolean; 
  onOpenChange: (open: boolean) => void;
  defaultPipelineId?: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: pipelines } = useProjectPipelines(projectId);
  const { data: environments } = useProjectEnvironments(projectId);
  const { mutateAsync: triggerRun, isPending } = useTriggerRun();
  
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors },
  } = useForm<TriggerFormInput, unknown, TriggerFormValues>({
    resolver: zodResolver(triggerSchema),
    defaultValues: {
      pipeline_id: defaultPipelineId ?? "",
      priority: 1,
    },
  });

  // eslint-disable-next-line react-hooks/incompatible-library -- React Hook Form watch drives local conditional UI state.
  const watchPipelineId = watch("pipeline_id");
  const selectedPipelineId = watchPipelineId ?? defaultPipelineId ?? "";
  const selectedEnvironmentId = watch("environment_id") ?? DEFAULT_ENVIRONMENT;
  const selectedPriority = String(watch("priority") ?? 1);

  useEffect(() => {
    if (defaultPipelineId) {
      setValue("pipeline_id", defaultPipelineId, { shouldValidate: true });
    }
  }, [defaultPipelineId, setValue]);

  const onSubmit: SubmitHandler<TriggerFormValues> = async (data) => {
    try {
      const run = await triggerRun({
        pipeline_id: data.pipeline_id,
        branch: data.branch || undefined,
        git_sha: data.git_sha || undefined,
        environment_id: data.environment_id || undefined,
        priority: data.priority,
      });
      toast.success(t("trigger.toast.success"));
      reset({ pipeline_id: defaultPipelineId ?? "", priority: 1 });
      onOpenChange(false);
      navigate(`/runs/${run.id}`);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t("trigger.toast.failed"));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{t("trigger.title")}</DialogTitle>
          <DialogDescription>{t("trigger.description")}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 py-4">
          <div className="space-y-2">
            <Label htmlFor="pipeline">{t("trigger.selectPipeline")}</Label>
            <Select 
              value={selectedPipelineId}
              onValueChange={(value) =>
                setValue("pipeline_id", value, {
                  shouldDirty: true,
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder={t("trigger.selectPipelinePlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {pipelines?.map(p => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.pipeline_id && <p className="text-xs text-status-failed">{t("validation.pipelineRequired")}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="branch">{t("trigger.branchOverride")}</Label>
            <Input id="branch" {...register("branch")} placeholder="e.g. develop" />
            <p className="text-[10px] text-ink-tertiary">{t("trigger.branchHint")}</p>
          </div>

          <div className="space-y-2">
            <Label>{t("trigger.selectEnvironment")}</Label>
            <Select
              value={selectedEnvironmentId}
              onValueChange={(value) =>
                setValue(
                  "environment_id",
                  value === DEFAULT_ENVIRONMENT ? undefined : value,
                  { shouldDirty: true },
                )
              }
            >
              <SelectTrigger>
                <SelectValue placeholder={t("trigger.selectEnvironmentPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_ENVIRONMENT}>
                  {t("trigger.projectDefaultEnvironment")}
                </SelectItem>
                {environments?.map((environment) => (
                  <SelectItem key={environment.id} value={environment.id}>
                    {environment.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="git_sha">{t("trigger.commitSha")}</Label>
            <Input
              id="git_sha"
              {...register("git_sha")}
              placeholder="0123456789abcdef0123456789abcdef01234567"
            />
            {errors.git_sha && (
              <p className="text-xs text-status-failed">
                {t("validation.gitShaInvalid")}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>{t("trigger.priority")}</Label>
            <Select
              value={selectedPriority}
              onValueChange={(value) =>
                setValue("priority", Number(value), { shouldDirty: true })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder={t("trigger.priorityPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="0">{t("priority.high")}</SelectItem>
                <SelectItem value="1">{t("priority.medium")}</SelectItem>
                <SelectItem value="2">{t("priority.low")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={isPending || !pipelines?.length}>
              {isPending ? t("trigger.triggering") : t("trigger.runPipeline")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
