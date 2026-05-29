import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";
import { useCreatePipeline } from "../../hooks/use-projects";
import { useUpdatePipeline, useDeletePipeline } from "../../hooks/use-pipelines";
import type { Pipeline, PipelineCreatePayload } from "../../types/api";
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
import { Checkbox } from "../../components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "../../components/ui/select";
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
import { useEffect } from "react";
import { Trash2 } from "lucide-react";

function createPipelineSchema() {
  return z.object({
    name: z.string().min(1, i18n.t('validation.nameRequired')),
    runner: z.string().min(1, i18n.t('validation.frameworkRequired')),
    include_paths: z.string().refine(
      (value) => parsePaths(value).length > 0,
      i18n.t('validation.patternRequired')
    ),
    timeout_seconds: z.number().min(1, i18n.t('validation.timeoutRequired')),
    collector_plugin: z.string().min(1),
    collector_path: z.string().min(1),
    trigger_type: z.enum(["manual", "webhook", "schedule"]),
    max_attempts: z.number().min(1).max(5),
    backoff_seconds: z.number().min(0),
    enabled: z.boolean(),
  });
}

type PipelineFormValues = z.infer<ReturnType<typeof createPipelineSchema>>;

const DEFAULT_TEST_PATHS = "tests";
const DEFAULT_COLLECTOR_PATH = "results/junit.xml";

function parsePaths(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((path) => path.trim())
    .filter(Boolean);
}

function pathsToText(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join("\n");
  if (typeof value === "string") return value;
  return "";
}

function pipelinePaths(pipeline: Pipeline): string {
  if (pipeline.selector.include_paths.length > 0) {
    return pipeline.selector.include_paths.join("\n");
  }
  return pathsToText(pipeline.stages[0]?.config.test_paths) || DEFAULT_TEST_PATHS;
}

function pipelineCollectorPath(pipeline: Pipeline): string {
  const config = pipeline.collectors?.[0]?.config ?? {};
  const path = config.path ?? config.junit_xml;
  return typeof path === "string" && path.trim() ? path : DEFAULT_COLLECTOR_PATH;
}

export function PipelineModal({
  projectId,
  pipeline,
  open,
  onOpenChange
}: {
  projectId: string;
  pipeline?: Pipeline;
  open: boolean;
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation();
  const isEditing = !!pipeline;
  const { mutateAsync: createPipeline, isPending: isCreating } = useCreatePipeline(projectId);
  const { mutateAsync: updatePipeline, isPending: isUpdating } = useUpdatePipeline(pipeline?.id ?? "", projectId);
  const { mutateAsync: deletePipeline } = useDeletePipeline(pipeline?.id ?? "", projectId);
  const pipelineSchema = createPipelineSchema();

  const {
    register,
    handleSubmit,
    control,
    setValue,
    reset,
    formState: { errors },
  } = useForm<PipelineFormValues>({
    resolver: zodResolver(pipelineSchema),
    defaultValues: {
      runner: "pytest",
      include_paths: DEFAULT_TEST_PATHS,
      timeout_seconds: 600,
      collector_plugin: "junit",
      collector_path: DEFAULT_COLLECTOR_PATH,
      trigger_type: "manual",
      max_attempts: 1,
      backoff_seconds: 0,
      enabled: true,
    },
  });

  useEffect(() => {
    if (pipeline) {
      reset({
        name: pipeline.name,
        runner: pipeline.stages[0]?.plugin ?? "pytest",
        include_paths: pipelinePaths(pipeline),
        timeout_seconds: pipeline.timeout_seconds,
        collector_plugin: pipeline.collectors?.[0]?.plugin ?? "junit",
        collector_path: pipelineCollectorPath(pipeline),
        trigger_type: (pipeline.trigger_config.type || "manual") as PipelineFormValues["trigger_type"],
        max_attempts: pipeline.retry_policy?.max_attempts ?? 1,
        backoff_seconds: pipeline.retry_policy?.backoff_seconds ?? 0,
        enabled: pipeline.enabled,
      });
    } else {
      reset({
        runner: "pytest",
        include_paths: DEFAULT_TEST_PATHS,
        timeout_seconds: 600,
        collector_plugin: "junit",
        collector_path: DEFAULT_COLLECTOR_PATH,
        trigger_type: "manual",
        max_attempts: 1,
        backoff_seconds: 0,
        enabled: true,
      });
    }
  }, [pipeline, reset]);

  const runner = useWatch({ control, name: "runner" });
  const triggerType = useWatch({ control, name: "trigger_type" });
  const collectorPlugin = useWatch({ control, name: "collector_plugin" });
  const enabled = useWatch({ control, name: "enabled" });

  const onSubmit = async (data: PipelineFormValues) => {
    try {
      const includePaths = parsePaths(data.include_paths);
      const payload: PipelineCreatePayload = {
        name: data.name,
        stages: [{
          name: "run-tests",
          plugin: data.runner,
          config: { test_paths: includePaths },
          continue_on_error: false,
          phase: "execute" as const,
        }],
        selector: {
          include_paths: includePaths,
          exclude_paths: [],
          tags: [],
          expression: null,
          regex: null,
          on_empty: "fail" as const,
        },
        timeout_seconds: data.timeout_seconds,
        collectors: [{
          plugin: data.collector_plugin,
          config: { path: data.collector_path },
          enabled: true,
        }],
        trigger_config: {
          type: data.trigger_type,
          dedup_window_seconds: null,
          source: {},
          conditions: {},
          target: {},
        },
        retry_policy: data.max_attempts > 1 ? {
          max_attempts: data.max_attempts,
          retry_on: ["infra"],
          backoff_seconds: data.backoff_seconds,
          scope: "pipeline" as const,
        } : null,
        enabled: data.enabled,
      };

      if (isEditing) {
        await updatePipeline(payload);
        toast.success(t('pipelines.toast.updated'));
      } else {
        await createPipeline(payload);
        toast.success(t('pipelines.toast.created'));
      }
      onOpenChange(false);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('pipelines.toast.actionFailed'));
    }
  };

  const onDelete = async () => {
    try {
      await deletePipeline();
      toast.success(t('pipelines.toast.deleted'));
      onOpenChange(false);
    } catch {
      toast.error(t('pipelines.toast.deleteFailed'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <div className="flex items-center justify-between pr-8">
            <DialogTitle>{isEditing ? t('pipelines.editPipeline') : t('pipelines.newPipeline')}</DialogTitle>
            {isEditing && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="ghost" size="sm" className="text-ink-tertiary hover:text-status-failed">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>{t('pipelines.deleteTitle')}</AlertDialogTitle>
                    <AlertDialogDescription>
                      {t('pipelines.deleteDescription')}
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                    <AlertDialogAction onClick={onDelete} className="bg-status-failed hover:bg-status-failed/90">{t('common.delete')}</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
          <DialogDescription>{t('pipelines.modalDescription')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="name">{t('pipelines.name')}</Label>
              <Input id="name" {...register("name")} placeholder="E2E Smoke Tests" />
              {errors.name && <p className="text-xs text-status-failed">{errors.name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="enabled" className="block mb-3">{t('pipelines.status')}</Label>
              <div className="flex items-center space-x-2 h-10">
                <Checkbox
                  id="enabled"
                  checked={enabled}
                  onCheckedChange={(checked) => setValue("enabled", checked === true)}
                />
                <label htmlFor="enabled" className="text-sm text-ink-muted">{t('pipelines.enabled')}</label>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="runner">{t('pipelines.framework')}</Label>
              <Select
                value={runner}
                onValueChange={(value) => setValue("runner", value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('pipelines.selectFramework')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pytest">Pytest</SelectItem>
                  <SelectItem value="jest">Jest</SelectItem>
                  <SelectItem value="playwright">Playwright</SelectItem>
                  <SelectItem value="go_test">Go Test</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="timeout">{t('pipelines.timeout')}</Label>
              <Input
                id="timeout"
                type="number"
                {...register("timeout_seconds", { valueAsNumber: true })}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="include_paths">{t('pipelines.testFilePattern')}</Label>
            <Input id="include_paths" {...register("include_paths")} placeholder="tests, tests/e2e" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="collector_plugin">{t('pipelines.collector')}</Label>
              <Select
                value={collectorPlugin}
                onValueChange={(value) => setValue("collector_plugin", value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('pipelines.collector')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="junit">JUnit XML</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="collector_path">{t('pipelines.collectorPath')}</Label>
              <Input
                id="collector_path"
                {...register("collector_path")}
                placeholder={DEFAULT_COLLECTOR_PATH}
              />
            </div>
          </div>

          <div className="space-y-4 rounded-lg border border-hairline p-4">
            <h4 className="text-sm font-medium">{t('pipelines.triggers')}</h4>
            <div className="space-y-2">
              <Label htmlFor="trigger_type">{t('pipelines.triggerType')}</Label>
              <Select
                value={triggerType}
                onValueChange={(value) => setValue("trigger_type", value as PipelineFormValues["trigger_type"])}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('pipelines.triggerType')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual">{t('pipelines.triggerManual')}</SelectItem>
                  <SelectItem value="webhook">{t('pipelines.triggerWebhook')}</SelectItem>
                  <SelectItem value="schedule">{t('pipelines.triggerSchedule')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="max_attempts">{t('pipelines.maxRetries')}</Label>
              <Input
                id="max_attempts"
                type="number"
                {...register("max_attempts", { valueAsNumber: true })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="backoff_seconds">{t('pipelines.backoffStrategy')}</Label>
              <Input
                id="backoff_seconds"
                type="number"
                {...register("backoff_seconds", { valueAsNumber: true })}
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
            <Button type="submit" disabled={isCreating || isUpdating}>
              {isEditing ? (isUpdating ? t('pipelines.saving') : t('pipelines.updatePipeline')) : (isCreating ? t('pipelines.creating') : t('pipelines.createPipeline'))}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
