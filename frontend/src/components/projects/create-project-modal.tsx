import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import i18n from "../../i18n";
import { discoverGitBranches, useCreateProject } from "../../hooks/use-projects";
import { isGitUrlAllowedForAuth } from "../../lib/contracts";
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
import { useEffect, useState } from "react";

function createProjectSchema() {
  return z.object({
    name: z.string().min(1, i18n.t('validation.nameRequired')),
    slug: z.string().min(1, i18n.t('validation.slugRequired')).regex(/^[a-z0-9-]+$/, i18n.t('validation.slugFormat')),
    description: z.string().optional(),
    git_url: z.string().min(1, i18n.t('validation.invalidUrl')),
    git_auth_method: z.enum(["none", "token", "ssh_key"]),
    default_branch: z.string().min(1, i18n.t('validation.defaultBranchRequired')),
    root_path: z.string().min(1, i18n.t('validation.rootPathRequired')),
  }).superRefine((value, context) => {
    if (!isGitUrlAllowedForAuth(value.git_url, value.git_auth_method)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["git_url"],
        message: i18n.t('validation.invalidUrl'),
      });
    }
  });
}

type ProjectFormValues = z.infer<ReturnType<typeof createProjectSchema>>;

export function CreateProjectModal({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { mutateAsync: createProject, isPending } = useCreateProject();
  const projectSchema = createProjectSchema();
  const [branches, setBranches] = useState<string[]>([]);
  const [branchStatus, setBranchStatus] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [branchMessage, setBranchMessage] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    control,
    getValues,
    setValue,
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

  const name = useWatch({ control, name: "name" });
  const gitUrl = useWatch({ control, name: "git_url" });
  const authMethod = useWatch({ control, name: "git_auth_method" });
  const defaultBranch = useWatch({ control, name: "default_branch" }) ?? "main";

  useEffect(() => {
    if (name) {
      setValue("slug", name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""));
    }
  }, [name, setValue]);

  useEffect(() => {
    if (!open) {
      const resetTimer = window.setTimeout(() => {
        setBranches([]);
        setBranchStatus("idle");
        setBranchMessage(null);
      }, 0);
      return () => window.clearTimeout(resetTimer);
    }

    const url = gitUrl?.trim();
    if (!url || !authMethod || !isGitUrlAllowedForAuth(url, authMethod)) {
      const resetTimer = window.setTimeout(() => {
        setBranches([]);
        setBranchStatus("idle");
        setBranchMessage(null);
      }, 0);
      return () => window.clearTimeout(resetTimer);
    }

    if (authMethod !== "none") {
      const resetTimer = window.setTimeout(() => {
        setBranches([]);
        setBranchStatus("idle");
        setBranchMessage(t("projects.form.branchDiscoveryPublicOnly"));
      }, 0);
      return () => window.clearTimeout(resetTimer);
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setBranchStatus("loading");
      setBranchMessage(null);
      try {
        const result = await discoverGitBranches({
          git_url: url,
          git_auth_method: authMethod,
        });
        if (cancelled) return;
        setBranches(result.branches);
        setBranchStatus("loaded");
        if (result.branches.length === 0) {
          setBranchMessage(t("projects.form.noBranchesFound"));
          return;
        }
        const preferred = result.default_branch && result.branches.includes(result.default_branch)
          ? result.default_branch
          : result.branches[0];
        const current = getValues("default_branch");
        if (!current || current === "main" || !result.branches.includes(current)) {
          setValue("default_branch", preferred, { shouldDirty: true, shouldValidate: true });
        }
        setBranchMessage(t("projects.form.branchesLoaded", { count: result.branches.length }));
      } catch (error: unknown) {
        if (cancelled) return;
        const axiosError = error as { response?: { data?: { detail?: string } } };
        setBranches([]);
        setBranchStatus("error");
        setBranchMessage(axiosError.response?.data?.detail || t("projects.form.branchLoadFailed"));
      }
    }, 500);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [authMethod, getValues, gitUrl, open, setValue, t]);

  const onSubmit = async (data: ProjectFormValues) => {
    try {
      const project = await createProject(data);
      toast.success(t('projects.toast.created'));
      reset();
      onOpenChange(false);
      navigate(`/projects/${project.id}`);
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
              {branches.length > 0 ? (
                <Select
                  value={defaultBranch}
                  onValueChange={(value) => setValue("default_branch", value, {
                    shouldDirty: true,
                    shouldValidate: true,
                  })}
                >
                  <SelectTrigger id="default_branch">
                    <SelectValue placeholder={t("projects.form.selectBranch")} />
                  </SelectTrigger>
                  <SelectContent>
                    {branches.map((branch) => (
                      <SelectItem key={branch} value={branch}>{branch}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input id="default_branch" {...register("default_branch")} placeholder="main" />
              )}
              {branchStatus === "loading" && (
                <p className="text-xs text-ink-tertiary">{t("projects.form.loadingBranches")}</p>
              )}
              {branchMessage && (
                <p className={branchStatus === "error" ? "text-xs text-status-failed" : "text-xs text-ink-tertiary"}>
                  {branchMessage}
                </p>
              )}
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
