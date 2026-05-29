import { useState } from "react";
import { Plus, Trash2, Eye, EyeOff, Save, X } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
  useProjectEnvironments,
  useCreateEnvironment,
  useUpdateEnvironment,
  useDeleteEnvironment
} from "../../hooks/use-projects";
import type { Environment } from "../../types/api";
import { isPinnedDockerImage } from "../../lib/contracts";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
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

const DEFAULT_ENVIRONMENT_BASE_IMAGE = "python:3.12-alpine";

export function EnvironmentEditor({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data: environments, isLoading } = useProjectEnvironments(projectId);
  const { mutateAsync: createEnv } = useCreateEnvironment(projectId);

  const [isAdding, setIsAdding] = useState(false);
  const [newEnvName, setNewEnvName] = useState("");
  const [newEnvBaseImage, setNewEnvBaseImage] = useState(DEFAULT_ENVIRONMENT_BASE_IMAGE);

  if (isLoading) return <div className="space-y-4 animate-pulse">
    <div className="h-32 bg-surface-1 rounded-lg" />
    <div className="h-32 bg-surface-1 rounded-lg" />
  </div>;

  const handleAdd = async () => {
    const name = newEnvName.trim();
    const baseImage = newEnvBaseImage.trim();
    if (!name || !baseImage) return;
    if (!isPinnedDockerImage(baseImage)) {
      toast.error(t('validation.invalidBaseImage'));
      return;
    }
    try {
      await createEnv({ name, base_image: baseImage, env_vars: {} });
      toast.success(t('environments.toast.created'));
      setNewEnvName("");
      setNewEnvBaseImage(DEFAULT_ENVIRONMENT_BASE_IMAGE);
      setIsAdding(false);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t('environments.toast.createFailed'));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium text-ink">{t('environments.title')}</h3>
        {!isAdding && (
          <Button size="sm" onClick={() => setIsAdding(true)}>
            <Plus className="mr-2 h-4 w-4" /> {t('environments.newEnvironment')}
          </Button>
        )}
      </div>

      {isAdding && (
        <div className="grid grid-cols-1 gap-4 rounded-lg border border-hairline bg-surface-1 p-4 animate-in fade-in slide-in-from-top-2 md:grid-cols-[1fr_1.2fr_auto] md:items-end">
          <div className="flex-1 space-y-2">
            <Label>{t('environments.envNameLabel')}</Label>
            <Input
              value={newEnvName}
              onChange={(e) => setNewEnvName(e.target.value)}
              placeholder="e.g. Production, Staging"
            />
          </div>
          <div className="flex-1 space-y-2">
            <Label>{t('environments.baseImageLabel')}</Label>
            <Input
              value={newEnvBaseImage}
              onChange={(e) => setNewEnvBaseImage(e.target.value)}
              placeholder={t('environments.baseImagePlaceholder')}
              className="font-mono text-xs"
            />
          </div>
          <div className="flex gap-2 md:justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setNewEnvName("");
                setNewEnvBaseImage(DEFAULT_ENVIRONMENT_BASE_IMAGE);
                setIsAdding(false);
              }}
            >
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={!newEnvName.trim() || !isPinnedDockerImage(newEnvBaseImage.trim())}
            >
              {t('common.create')}
            </Button>
          </div>
        </div>
      )}

      <div className="grid gap-6">
        {environments?.length === 0 ? (
          <div className="rounded-xl border border-hairline border-dashed p-12 text-center text-sm text-ink-tertiary">
            {t('environments.noEnvironments')}
          </div>
        ) : (
          environments?.map(env => (
            <EnvironmentCard
              key={`${env.id}:${JSON.stringify(env.variables)}`}
              env={env}
              projectId={projectId}
            />
          ))
        )}
      </div>
    </div>
  );
}

function EnvironmentCard({ env, projectId }: { env: Environment; projectId: string }) {
  const { t } = useTranslation();
  const [variables, setVariables] = useState(env.variables);
  const [isEditing, setIsEditing] = useState(false);
  const [showValues, setShowValues] = useState<Record<string, boolean>>({});

  const { mutateAsync: updateEnv } = useUpdateEnvironment(projectId, env.id);
  const { mutateAsync: deleteEnv } = useDeleteEnvironment(projectId, env.id);

  const handleSave = async () => {
    try {
      await updateEnv({ env_vars: variables });
      toast.success(t('environments.toast.saved'));
      setIsEditing(false);
    } catch {
      toast.error(t('environments.toast.saveFailed'));
    }
  };

  const handleDelete = async () => {
    try {
      await deleteEnv();
      toast.success(t('environments.toast.deleted'));
    } catch {
      toast.error(t('environments.toast.deleteFailed'));
    }
  };

  const addVariable = () => {
    setVariables({ ...variables, "": "" });
    setIsEditing(true);
  };

  const removeVariable = (key: string) => {
    const newVars = { ...variables };
    delete newVars[key];
    setVariables(newVars);
    setIsEditing(true);
  };

  const updateKey = (oldKey: string, newKey: string) => {
    if (oldKey === newKey) return;
    const newVars = { ...variables };
    newVars[newKey] = newVars[oldKey];
    delete newVars[oldKey];
    setVariables(newVars);
    setIsEditing(true);
  };

  const updateValue = (key: string, value: string) => {
    setVariables({ ...variables, [key]: value });
    setIsEditing(true);
  };

  const toggleShow = (key: string) => {
    setShowValues({ ...showValues, [key]: !showValues[key] });
  };

  return (
    <div className="rounded-xl border border-hairline bg-surface-1 overflow-hidden transition-all hover:border-hairline-strong">
      <div className="bg-surface-2/50 px-6 py-4 flex items-center justify-between border-b border-hairline">
        <h4 className="font-medium text-ink">{env.name}</h4>
        <div className="flex gap-2">
          {isEditing && (
            <Button size="sm" variant="ghost" className="text-status-passed hover:bg-status-passed/5" onClick={handleSave}>
              <Save className="mr-2 h-4 w-4" /> {t('common.save')}
            </Button>
          )}
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button size="sm" variant="ghost" className="text-ink-tertiary hover:text-status-failed">
                <Trash2 className="h-4 w-4" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t('environments.deleteTitle')}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t('environments.deleteDescription', { name: env.name })}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                <AlertDialogAction onClick={handleDelete} className="bg-status-failed hover:bg-status-failed/90">{t('common.delete')}</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      <div className="p-6 space-y-4">
        <div className="space-y-3">
          {Object.entries(variables).map(([key, value]) => (
            <div key={key} className="flex gap-3 items-start">
              <div className="flex-1">
                <Input
                  value={key}
                  onChange={(e) => updateKey(key, e.target.value)}
                  placeholder="KEY"
                  className="font-mono text-xs h-9"
                />
              </div>
              <div className="flex-[2] relative">
                <Input
                  type={showValues[key] ? "text" : "password"}
                  value={value as string}
                  onChange={(e) => updateValue(key, e.target.value)}
                  placeholder="VALUE"
                  className="font-mono text-xs h-9 pr-10"
                />
                <button
                  type="button"
                  onClick={() => toggleShow(key)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink"
                  aria-label={showValues[key] ? "Hide value" : "Show value"}
                >
                  {showValues[key] ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                </button>
              </div>
              <Button variant="ghost" size="sm" onClick={() => removeVariable(key)} className="text-ink-tertiary">
                <X className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>

        <Button variant="ghost" size="sm" onClick={addVariable} className="text-ink-subtle hover:text-ink">
          <Plus className="mr-2 h-4 w-4" /> {t('environments.addVariable')}
        </Button>
      </div>
    </div>
  );
}
