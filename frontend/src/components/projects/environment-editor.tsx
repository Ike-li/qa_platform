import { useState } from "react";
import { Plus, Trash2, Eye, EyeOff, Save, X } from "lucide-react";
import { toast } from "sonner";
import {
  useProjectEnvironments,
  useCreateEnvironment,
  useUpdateEnvironment,
  useDeleteEnvironment
} from "../../hooks/use-projects";
import type { Environment } from "../../types/api";
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

export function EnvironmentEditor({ projectId }: { projectId: string }) {
  const { data: environments, isLoading } = useProjectEnvironments(projectId);
  const { mutateAsync: createEnv } = useCreateEnvironment(projectId);

  const [isAdding, setIsAdding] = useState(false);
  const [newEnvName, setNewEnvName] = useState("");

  if (isLoading) return <div className="space-y-4 animate-pulse">
    <div className="h-32 bg-surface-1 rounded-lg" />
    <div className="h-32 bg-surface-1 rounded-lg" />
  </div>;

  const handleAdd = async () => {
    if (!newEnvName) return;
    try {
      await createEnv({ name: newEnvName, variables: {} });
      toast.success("Environment created");
      setNewEnvName("");
      setIsAdding(false);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || "Failed to create environment");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium text-ink">Environments</h3>
        {!isAdding && (
          <Button size="sm" onClick={() => setIsAdding(true)}>
            <Plus className="mr-2 h-4 w-4" /> New Environment
          </Button>
        )}
      </div>

      {isAdding && (
        <div className="rounded-lg border border-hairline bg-surface-1 p-4 flex items-end gap-4 animate-in fade-in slide-in-from-top-2">
          <div className="flex-1 space-y-2">
            <Label>Environment Name</Label>
            <Input 
              value={newEnvName} 
              onChange={(e) => setNewEnvName(e.target.value)} 
              placeholder="e.g. Production, Staging" 
            />
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setIsAdding(false)}>Cancel</Button>
            <Button size="sm" onClick={handleAdd}>Create</Button>
          </div>
        </div>
      )}

      <div className="grid gap-6">
        {environments?.length === 0 ? (
          <div className="rounded-xl border border-hairline border-dashed p-12 text-center text-sm text-ink-tertiary">
            No environments configured.
          </div>
        ) : (
          environments?.map(env => (
            <EnvironmentCard 
              key={env.id} 
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
  const [variables, setVariables] = useState(env.variables);
  const [isEditing, setIsEditing] = useState(false);
  const [showValues, setShowValues] = useState<Record<string, boolean>>({});

  const { mutateAsync: updateEnv } = useUpdateEnvironment(projectId, env.id);
  const { mutateAsync: deleteEnv } = useDeleteEnvironment(projectId, env.id);

  const handleSave = async () => {
    try {
      await updateEnv({ ...env, variables });
      toast.success("Environment variables saved");
      setIsEditing(false);
    } catch (error: unknown) {
      toast.error("Failed to save variables");
    }
  };

  const handleDelete = async () => {
    try {
      await deleteEnv();
      toast.success("Environment deleted");
    } catch (error: unknown) {
      toast.error("Failed to delete environment");
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
              <Save className="mr-2 h-4 w-4" /> Save
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
                <AlertDialogTitle>Delete Environment?</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to delete the "{env.name}" environment? All variables will be lost.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={handleDelete} className="bg-status-failed hover:bg-status-failed/90">Delete</AlertDialogAction>
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
          <Plus className="mr-2 h-4 w-4" /> Add variable
        </Button>
      </div>
    </div>
  );
}
