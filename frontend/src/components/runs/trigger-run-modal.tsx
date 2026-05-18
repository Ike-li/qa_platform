import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTriggerRun } from "../../hooks/use-runs";
import { useProjectPipelines } from "../../hooks/use-projects";
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

const triggerSchema = z.object({
  pipeline_id: z.string().min(1),
  branch: z.string().optional(),
});

type TriggerFormValues = z.infer<typeof triggerSchema>;

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
  const { mutateAsync: triggerRun, isPending } = useTriggerRun();
  
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors },
  } = useForm<TriggerFormValues>({
    resolver: zodResolver(triggerSchema),
    defaultValues: {
      pipeline_id: defaultPipelineId,
    },
  });

  const watchPipelineId = watch("pipeline_id");

  const onSubmit = async (data: TriggerFormValues) => {
    try {
      const run = await triggerRun({
        pipeline_id: data.pipeline_id,
        branch: data.branch || undefined,
      });
      toast.success(t("trigger.toast.success"));
      reset();
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
              value={watchPipelineId || defaultPipelineId}
              onValueChange={(value) => setValue("pipeline_id", value)}
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
