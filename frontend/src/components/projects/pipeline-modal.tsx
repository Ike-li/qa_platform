import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
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

const pipelineSchema = z.object({
  name: z.string().min(1, "Name is required"),
  framework: z.string().min(1, "Framework is required"),
  pattern: z.string().min(1, "Pattern is required"),
  timeout_seconds: z.number().min(1, "Timeout is required"),
  on_push: z.boolean(),
  schedule: z.string().optional().nullable(),
  max_retries: z.number().min(0),
  backoff: z.enum(["fixed", "exponential"]),
  enabled: z.boolean(),
});

type PipelineFormValues = z.infer<typeof pipelineSchema>;

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
  const isEditing = !!pipeline;
  const { mutateAsync: createPipeline, isPending: isCreating } = useCreatePipeline(projectId);
  const { mutateAsync: updatePipeline, isPending: isUpdating } = useUpdatePipeline(pipeline?.id ?? "", projectId);
  const { mutateAsync: deletePipeline } = useDeletePipeline(pipeline?.id ?? "", projectId);
  
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
        toast.success("Pipeline updated");
      } else {
        await createPipeline(payload as Partial<Pipeline>);
        toast.success("Pipeline created");
      }
      onOpenChange(false);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || "Action failed");
    }
  };

  const onDelete = async () => {
    try {
      await deletePipeline();
      toast.success("Pipeline deleted");
      onOpenChange(false);
    } catch (error: unknown) {
      toast.error("Failed to delete pipeline");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <div className="flex items-center justify-between pr-8">
            <DialogTitle>{isEditing ? "Edit Pipeline" : "New Pipeline"}</DialogTitle>
            {isEditing && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="ghost" size="sm" className="text-ink-tertiary hover:text-status-failed">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete Pipeline?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Are you sure you want to delete this pipeline? This will remove its configuration and trigger history.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={onDelete} className="bg-status-failed hover:bg-status-failed/90">Delete</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
          <DialogDescription>Define how your tests should be discovered and executed.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="name">Pipeline Name</Label>
              <Input id="name" {...register("name")} placeholder="E2E Smoke Tests" />
              {errors.name && <p className="text-xs text-status-failed">{errors.name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="enabled" className="block mb-3">Status</Label>
              <div className="flex items-center space-x-2 h-10">
                <Checkbox 
                  id="enabled" 
                  checked={enabled} 
                  onCheckedChange={(checked) => setValue("enabled", checked === true)} 
                />
                <label htmlFor="enabled" className="text-sm text-ink-muted">Enabled</label>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="framework">Framework</Label>
              <Select 
                value={watch("framework")}
                onValueChange={(value) => setValue("framework", value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select framework" />
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
              <Label htmlFor="timeout">Timeout (seconds)</Label>
              <Input 
                id="timeout" 
                type="number" 
                {...register("timeout_seconds", { valueAsNumber: true })} 
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="pattern">Test File Pattern</Label>
            <Input id="pattern" {...register("pattern")} placeholder="tests/**/*.py" />
          </div>

          <div className="space-y-4 rounded-lg border border-hairline p-4">
            <h4 className="text-sm font-medium">Triggers</h4>
            <div className="flex items-center space-x-2">
              <Checkbox 
                id="on_push" 
                checked={onPush} 
                onCheckedChange={(checked) => setValue("on_push", checked === true)} 
              />
              <label htmlFor="on_push" className="text-sm text-ink-muted">Run on every push to default branch</label>
            </div>
            <div className="space-y-2">
              <Label htmlFor="schedule">Cron Schedule (Optional)</Label>
              <Input id="schedule" {...register("schedule")} placeholder="0 0 * * *" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="max_retries">Max Retries</Label>
              <Input 
                id="max_retries" 
                type="number" 
                {...register("max_retries", { valueAsNumber: true })} 
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="backoff">Backoff Strategy</Label>
              <Select 
                value={watch("backoff")}
                onValueChange={(value) => setValue("backoff", value as "fixed" | "exponential")}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select strategy" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fixed">Fixed</SelectItem>
                  <SelectItem value="exponential">Exponential</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={isCreating || isUpdating}>
              {isEditing ? (isUpdating ? "Saving..." : "Update Pipeline") : (isCreating ? "Creating..." : "Create Pipeline")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
