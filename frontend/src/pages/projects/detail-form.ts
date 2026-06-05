import { z } from "zod";
import i18n from "../../i18n";
import { isGitUrl } from "../../lib/contracts";

export function createProjectSchema() {
  return z.object({
    name: z.string().min(1, i18n.t('validation.nameRequired')),
    description: z.string().optional(),
    git_url: z.string().min(1, i18n.t('validation.invalidUrl')).refine(isGitUrl, i18n.t('validation.invalidUrl')),
    default_branch: z.string().min(1, i18n.t('validation.defaultBranchRequired')),
    root_path: z.string().min(1, i18n.t('validation.rootPathRequired')),
  });
}

export type ProjectFormValues = z.infer<ReturnType<typeof createProjectSchema>>;
