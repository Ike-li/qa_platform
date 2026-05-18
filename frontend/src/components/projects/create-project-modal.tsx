import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";
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

function createProjectSchema() {
  return z.object({
    name: z.string().min(1, i18n.t('validation.nameRequired')),
    slug: z.string().min(1, i18n.t('validation.slugRequired')).regex(/^[a-z0-9-]+$/, i18n.t('validation.slugFormat')),
    description: z.string().optional(),
    git_url: z.string().url(i18n.t('validation.invalidUrl')),
    git_auth_method: z.enum(["none", "token", "ssh_key"]),
    default_branch: z.string().min(1, i18n.t('validation.defaultBranchRequired')),
    root_path: z.string().min(1, i18n.t('validation.rootPathRequired')),
  });
}

type ProjectFormValues = z.infer<ReturnType<typeof createProjectSchema>>;

export function CreateProjectModal({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const { mutateAsync: createProject, isPending } = useCreateProject();
  const projectSchema = createProjectSchema();

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
      toast.success(t('projects.toast.created'));
      reset();
      onOpenChange(false);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('projects.toast.createFailed'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{t('projects.newProject')}</DialogTitle>
          <DialogDescription>{t('projects.createDescription')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="name">{t('projects.form.name')}</Label>
              <Input id="name" {...register("name")} placeholder="My Awesome Project" />
              {errors.name && <p className="text-xs text-status-failed">{errors.name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="slug">{t('projects.form.slug')}</Label>
              <Input id="slug" {...register("slug")} placeholder="my-awesome-project" />
              {errors.slug && <p className="text-xs text-status-failed">{errors.slug.message}</p>}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t('projects.form.descriptionOptional')}</Label>
            <Textarea id="description" {...register("description")} placeholder="Describe your project..." />
          </div>

          <div className="space-y-2">
            <Label htmlFor="git_url">{t('projects.form.gitUrl')}</Label>
            <Input id="git_url" {...register("git_url")} placeholder="https://github.com/org/repo.git" />
            {errors.git_url && <p className="text-xs text-status-failed">{errors.git_url.message}</p>}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="git_auth_method">{t('projects.form.authMethod')}</Label>
              <Select
                defaultValue="none"
                onValueChange={(value) => setValue("git_auth_method", value as "none" | "token" | "ssh_key")}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select method" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t('projects.form.authNone')}</SelectItem>
                  <SelectItem value="token">{t('projects.form.authToken')}</SelectItem>
                  <SelectItem value="ssh_key">{t('projects.form.authSshKey')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="default_branch">{t('projects.form.defaultBranch')}</Label>
              <Input id="default_branch" {...register("default_branch")} placeholder="main" />
              {errors.default_branch && <p className="text-xs text-status-failed">{errors.default_branch.message}</p>}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="root_path">{t('projects.form.rootPath')}</Label>
            <Input id="root_path" {...register("root_path")} placeholder="/" />
            {errors.root_path && <p className="text-xs text-status-failed">{errors.root_path.message}</p>}
          </div>

          <DialogFooter className="pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? t('projects.form.creating') : t('projects.form.createProject')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
