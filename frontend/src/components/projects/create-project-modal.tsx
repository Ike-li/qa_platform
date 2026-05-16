import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useCreateProject } from "../../hooks/use-projects";
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
import { Textarea } from "../../components/ui/textarea";
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from "../../components/ui/select";
import { useEffect } from "react";

const projectSchema = z.object({
  name: z.string().min(1, "Name is required"),
  slug: z.string().min(1, "Slug is required").regex(/^[a-z0-9-]+$/, "Slug must be lowercase and contain only letters, numbers, and hyphens"),
  description: z.string().optional(),
  git_url: z.string().url("Invalid Git URL"),
  git_auth_method: z.enum(["none", "token", "ssh_key"]),
  default_branch: z.string().min(1, "Default branch is required"),
  root_path: z.string().min(1, "Root path is required"),
});

type ProjectFormValues = z.infer<typeof projectSchema>;

export function CreateProjectModal({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { mutateAsync: createProject, isPending } = useCreateProject();
  
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors },
  } = useForm<ProjectFormValues>({
    resolver: zodResolver(projectSchema),
    defaultValues: {
      git_auth_method: "none",
      default_branch: "main",
      root_path: "/",
    },
  });

  const name = watch("name");
  useEffect(() => {
    if (name) {
      setValue("slug", name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""));
    }
  }, [name, setValue]);

  const onSubmit = async (data: ProjectFormValues) => {
    try {
      await createProject(data);
      toast.success("Project created successfully");
      reset();
      onOpenChange(false);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || "Failed to create project");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>New Project</DialogTitle>
          <DialogDescription>Create a new automation project to start running tests.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" {...register("name")} placeholder="My Awesome Project" />
              {errors.name && <p className="text-xs text-status-failed">{errors.name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="slug">Slug</Label>
              <Input id="slug" {...register("slug")} placeholder="my-awesome-project" />
              {errors.slug && <p className="text-xs text-status-failed">{errors.slug.message}</p>}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description (Optional)</Label>
            <Textarea id="description" {...register("description")} placeholder="Describe your project..." />
          </div>

          <div className="space-y-2">
            <Label htmlFor="git_url">Git Repository URL</Label>
            <Input id="git_url" {...register("git_url")} placeholder="https://github.com/org/repo.git" />
            {errors.git_url && <p className="text-xs text-status-failed">{errors.git_url.message}</p>}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="git_auth_method">Auth Method</Label>
              <Select 
                defaultValue="none" 
                onValueChange={(value) => setValue("git_auth_method", value as "none" | "token" | "ssh_key")}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select method" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None / Public</SelectItem>
                  <SelectItem value="token">Personal Access Token</SelectItem>
                  <SelectItem value="ssh_key">SSH Key</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="default_branch">Default Branch</Label>
              <Input id="default_branch" {...register("default_branch")} placeholder="main" />
              {errors.default_branch && <p className="text-xs text-status-failed">{errors.default_branch.message}</p>}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="root_path">Root Path</Label>
            <Input id="root_path" {...register("root_path")} placeholder="/" />
            {errors.root_path && <p className="text-xs text-status-failed">{errors.root_path.message}</p>}
          </div>

          <DialogFooter className="pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? "Creating..." : "Create Project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
