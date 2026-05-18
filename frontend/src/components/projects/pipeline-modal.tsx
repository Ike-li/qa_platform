import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";
import { useCreatePipeline } from "../../hooks/use-projects";
import { useUpdatePipeline, useDeletePipeline } from "../../hooks/use-pipelines";
import type { Pipeline } from "../../types/api";
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
    framework: z.string().min(1, i18n.t('validation.frameworkRequired')),
    pattern: z.string().min(1, i18n.t('validation.patternRequired')),
    timeout_seconds: z.number().min(1, i18n.t('validation.timeoutRequired')),
    on_push: z.boolean(),
    schedule: z.string().optional().nullable(),
    max_retries: z.number().min(0),
    backoff: z.enum(["fixed", "exponential"]),
    enabled: z.boolean(),
  });
}

type PipelineFormValues = z.infer<ReturnType<typeof createPipelineSchema>>;

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
    setValue,
    watch,
    reset,
    formState: { errors },
  } = useForm<PipelineFormValues>({
    resolver: zodResolver(pipelineSchema),
    defaultValues: {
      framework: "pytest",
      pattern: "tests/**/*.py",
      timeout_seconds: 600,
      on_push: true,
      max_retries: 0,
      backoff: "fixed",
      enabled: true,
    },
  });

  useEffect(() => {
    if (pipeline) {
      reset({
        name: pipeline.name,
        framework: pipeline.selector.framework,
        pattern: pipeline.selector.pattern,
        timeout_seconds: pipeline.timeout_seconds,
        on_push: pipeline.trigger_config.on_push,
        schedule: pipeline.trigger_config.on_schedule || "",
        max_retries: pipeline.retry_policy?.max_retries || 0,
        backoff: pipeline.retry_policy?.backoff || "fixed",
        enabled: pipeline.enabled,
      });
    } else {
      reset({
        framework: "pytest",
        pattern: "tests/**/*.py",
        timeout_seconds: 600,
        on_push: true,
        max_retries: 0,
        backoff: "fixed",
        enabled: true,
      });
    }
  }, [pipeline, reset]);

  const onPush = watch("on_push");
  const enabled = watch("enabled");

  const onSubmit = async (data: PipelineFormValues) => {
    try {
      const payload = {
        name: data.name,
        selector: {
          framework: data.framework,
          pattern: data.pattern,
        },
        timeout_seconds: data.timeout_seconds,
        trigger_config: {
          on_push: data.on_push,
          on_schedule: data.schedule || null,
        },
        retry_policy: data.max_retries > 0 ? {
          max_retries: data.max_retries,
          backoff: data.backoff,
        } : null,
        enabled: data.enabled,
      };

      if (isEditing) {
        await updatePipeline(payload as Partial<Pipeline>);
        toast.success(t('pipelines.toast.updated'));
      } else {
        await createPipeline(payload as Partial<Pipeline>);
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
              <Label htmlFor="framework">{t('pipelines.framework')}</Label>
              <Select
                value={watch("framework")}
                onValueChange={(value) => setValue("framework", value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('pipelines.selectFramework')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pytest">Pytest</SelectItem>
                  <SelectItem value="jest">Jest</SelectItem>
                  <SelectItem value="playwright">Playwright</SelectItem>
                  <SelectItem value="cypress">Cypress</SelectItem>
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
            <Label htmlFor="pattern">{t('pipelines.testFilePattern')}</Label>
            <Input id="pattern" {...register("pattern")} placeholder="tests/**/*.py" />
          </div>

          <div className="space-y-4 rounded-lg border border-hairline p-4">
            <h4 className="text-sm font-medium">{t('pipelines.triggers')}</h4>
            <div className="flex items-center space-x-2">
              <Checkbox
                id="on_push"
                checked={onPush}
                onCheckedChange={(checked) => setValue("on_push", checked === true)}
              />
              <label htmlFor="on_push" className="text-sm text-ink-muted">{t('pipelines.onPush')}</label>
            </div>
            <div className="space-y-2">
              <Label htmlFor="schedule">{t('pipelines.cronSchedule')}</Label>
              <Input id="schedule" {...register("schedule")} placeholder="0 0 * * *" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="max_retries">{t('pipelines.maxRetries')}</Label>
              <Input
                id="max_retries"
                type="number"
                {...register("max_retries", { valueAsNumber: true })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="backoff">{t('pipelines.backoffStrategy')}</Label>
              <Select
                value={watch("backoff")}
                onValueChange={(value) => setValue("backoff", value as "fixed" | "exponential")}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('pipelines.selectStrategy')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fixed">{t('pipelines.backoffFixed')}</SelectItem>
                  <SelectItem value="exponential">{t('pipelines.backoffExponential')}</SelectItem>
                </SelectContent>
              </Select>
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
