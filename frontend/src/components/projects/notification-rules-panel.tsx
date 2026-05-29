import { useState } from "react";
import {
  Plus,
  Trash2,
  Save,
  X,
  Pencil,
  Bell,
  BellOff,
  Mail,
  Webhook,
} from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
  useNotificationRules,
  useCreateNotificationRule,
  useUpdateNotificationRule,
  useDeleteNotificationRule,
} from "../../hooks/use-notifications";
import type {
  NotificationRule,
  NotificationCondition,
  NotificationChannel,
} from "../../types/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";
import { Switch } from "../ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../ui/alert-dialog";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const CONDITION_FIELDS: NotificationCondition["field"][] = [
  "status",
  "pass_rate",
  "failed",
];

const CONDITION_OPS: NotificationCondition["operator"][] = [
  "eq",
  "ne",
  "lt",
  "gt",
  "lte",
  "gte",
];

const CHANNEL_TYPES: NotificationChannel["type"][] = ["email", "webhook"];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function emptyCondition(): NotificationCondition {
  return { field: "status", operator: "eq", value: "" };
}

function emptyChannel(): NotificationChannel {
  return { type: "email", config: {} };
}

/* ------------------------------------------------------------------ */
/*  Main Panel                                                         */
/* ------------------------------------------------------------------ */

export function NotificationRulesPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data: rules, isLoading } = useNotificationRules(projectId);

  const [editingRule, setEditingRule] = useState<NotificationRule | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const startCreate = () => {
    setEditingRule(null);
    setIsCreating(true);
  };

  const startEdit = (rule: NotificationRule) => {
    setIsCreating(false);
    setEditingRule(rule);
  };

  const cancelForm = () => {
    setEditingRule(null);
    setIsCreating(false);
  };

  if (isLoading)
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-32 bg-surface-1 rounded-lg" />
        <div className="h-32 bg-surface-1 rounded-lg" />
      </div>
    );

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium text-ink">
          {t("notifications.title")}
        </h3>
        {!isCreating && !editingRule && (
          <Button size="sm" onClick={startCreate}>
            <Plus className="mr-2 h-4 w-4" /> {t("notifications.create")}
          </Button>
        )}
      </div>

      {(isCreating || editingRule) && (
        <RuleForm
          projectId={projectId}
          rule={editingRule}
          onCancel={cancelForm}
        />
      )}

      <div className="grid gap-4">
        {rules?.length === 0 ? (
          <div className="rounded-xl border border-hairline border-dashed p-12 text-center text-sm text-ink-tertiary">
            {t("notifications.noRules")}
          </div>
        ) : (
          rules?.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              projectId={projectId}
              onEdit={() => startEdit(rule)}
            />
          ))
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Rule Card                                                          */
/* ------------------------------------------------------------------ */

function RuleCard({
  rule,
  projectId,
  onEdit,
}: {
  rule: NotificationRule;
  projectId: string;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const { mutateAsync: deleteRule } = useDeleteNotificationRule(
    projectId,
    rule.id
  );

  const handleDelete = async () => {
    try {
      await deleteRule();
      toast.success(t("notifications.toast.deleted"));
    } catch {
      toast.error(t("notifications.toast.deleteFailed"));
    }
  };

  return (
    <div className="rounded-xl border border-hairline bg-surface-1 overflow-hidden transition-all hover:border-hairline-strong">
      <div className="bg-surface-2/50 px-6 py-4 flex items-center justify-between border-b border-hairline">
        <div className="flex items-center gap-3">
          {rule.enabled ? (
            <Bell className="h-4 w-4 text-status-passed" />
          ) : (
            <BellOff className="h-4 w-4 text-ink-tertiary" />
          )}
          <h4 className="font-medium text-ink">{rule.name}</h4>
          {!rule.enabled && (
            <span className="text-xs text-ink-tertiary">
              ({t("notifications.disabled")})
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            className="text-ink-tertiary hover:text-ink"
            onClick={onEdit}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                size="sm"
                variant="ghost"
                className="text-ink-tertiary hover:text-status-failed"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  {t("notifications.deleteTitle")}
                </AlertDialogTitle>
                <AlertDialogDescription>
                  {t("notifications.deleteDescription", { name: rule.name })}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleDelete}
                  className="bg-status-failed hover:bg-status-failed/90"
                >
                  {t("common.delete")}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      <div className="p-6 grid grid-cols-3 gap-4 text-sm">
        <div>
          <span className="text-ink-muted">
            {t("notifications.conditions")}
          </span>
          <p className="text-ink font-medium">
            {rule.conditions.length} {t("notifications.conditionsCount", { count: rule.conditions.length })}
          </p>
        </div>
        <div>
          <span className="text-ink-muted">
            {t("notifications.channels")}
          </span>
          <div className="flex gap-2 mt-1">
            {rule.channels.map((ch, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-xs text-ink-muted"
              >
                {ch.type === "email" ? (
                  <Mail className="h-3 w-3" />
                ) : (
                  <Webhook className="h-3 w-3" />
                )}
                {ch.type}
              </span>
            ))}
          </div>
        </div>
        <div>
          <span className="text-ink-muted">
            {t("notifications.template")}
          </span>
          <p className="text-ink font-medium truncate">
            {rule.template || "—"}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Rule Form (Create / Edit)                                          */
/* ------------------------------------------------------------------ */

function RuleForm({
  projectId,
  rule,
  onCancel,
}: {
  projectId: string;
  rule: NotificationRule | null;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const isEditing = rule !== null;

  const [name, setName] = useState(rule?.name ?? "");
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [conditions, setConditions] = useState<NotificationCondition[]>(
    rule?.conditions ?? [emptyCondition()]
  );
  const [channels, setChannels] = useState<NotificationChannel[]>(
    rule?.channels ?? [emptyChannel()]
  );
  const [template, setTemplate] = useState(rule?.template ?? "");

  const { mutateAsync: createRule, isPending: isCreating } =
    useCreateNotificationRule(projectId);
  const { mutateAsync: updateRule, isPending: isUpdating } =
    useUpdateNotificationRule(projectId, rule?.id ?? "");

  const isPending = isCreating || isUpdating;

  /* ---- condition helpers ---- */
  const updateCondition = (
    index: number,
    patch: Partial<NotificationCondition>
  ) => {
    setConditions((prev) =>
      prev.map((c, i) => (i === index ? { ...c, ...patch } : c))
    );
  };
  const removeCondition = (index: number) =>
    setConditions((prev) => prev.filter((_, i) => i !== index));

  /* ---- channel helpers ---- */
  const updateChannel = (
    index: number,
    patch: Partial<NotificationChannel>
  ) => {
    setChannels((prev) =>
      prev.map((c, i) => (i === index ? { ...c, ...patch } : c))
    );
  };
  const updateChannelConfig = (
    index: number,
    key: string,
    value: string
  ) => {
    setChannels((prev) =>
      prev.map((c, i) =>
        i === index
          ? { ...c, config: { ...c.config, [key]: value } }
          : c
      )
    );
  };
  const removeChannel = (index: number) =>
    setChannels((prev) => (
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)
    ));

  /* ---- submit ---- */
  const handleSave = async () => {
    if (!name.trim()) return;
    if (channels.length === 0) {
      toast.error(t("notifications.channelsRequired"));
      return;
    }
    try {
      const payload = {
        name: name.trim(),
        enabled,
        conditions,
        channels,
        template: template.trim() || null,
      };
      if (isEditing) {
        await updateRule(payload);
        toast.success(t("notifications.toast.updated"));
      } else {
        await createRule(payload);
        toast.success(t("notifications.toast.created"));
      }
      onCancel();
    } catch (error: unknown) {
      const axiosError = error as {
        response?: { data?: { detail?: string } };
      };
      toast.error(
        axiosError.response?.data?.detail ||
          t("notifications.toast.actionFailed")
      );
    }
  };

  return (
    <div className="rounded-xl border border-hairline bg-surface-1 p-6 space-y-6 animate-in fade-in slide-in-from-top-2">
      <h4 className="font-medium text-ink">
        {isEditing ? t("notifications.edit") : t("notifications.create")}
      </h4>

      {/* Name + Enabled */}
      <div className="flex items-end gap-4">
        <div className="flex-1 space-y-2">
          <Label>{t("notifications.name")}</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Failed build alert"
          />
        </div>
        <div className="flex items-center gap-2 pb-0.5">
          <Switch checked={enabled} onCheckedChange={setEnabled} />
          <Label className="cursor-pointer">
            {t("notifications.enabled")}
          </Label>
        </div>
      </div>

      {/* Conditions */}
      <div className="space-y-3">
        <Label>{t("notifications.conditions")}</Label>
        {conditions.map((cond, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <Select
              value={cond.field}
              onValueChange={(v) =>
                updateCondition(idx, {
                  field: v as NotificationCondition["field"],
                })
              }
            >
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONDITION_FIELDS.map((f) => (
                  <SelectItem key={f} value={f}>
                    {f}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={cond.operator}
              onValueChange={(v) =>
                updateCondition(idx, {
                  operator: v as NotificationCondition["operator"],
                })
              }
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONDITION_OPS.map((op) => (
                  <SelectItem key={op} value={op}>
                    {op}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Input
              className="flex-1"
              value={String(cond.value)}
              onChange={(e) => updateCondition(idx, { value: e.target.value })}
              placeholder="value"
            />

            <Button
              variant="ghost"
              size="sm"
              onClick={() => removeCondition(idx)}
              className="text-ink-tertiary"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            setConditions((prev) => [...prev, emptyCondition()])
          }
          className="text-ink-subtle hover:text-ink"
        >
          <Plus className="mr-2 h-4 w-4" /> {t("notifications.addCondition")}
        </Button>
      </div>

      {/* Channels */}
      <div className="space-y-3">
        <Label>{t("notifications.channels")}</Label>
        {channels.map((ch, idx) => (
          <div key={idx} className="flex items-start gap-2">
            <Select
              value={ch.type}
              onValueChange={(v) =>
                updateChannel(idx, {
                  type: v as NotificationChannel["type"],
                  config: {},
                })
              }
            >
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CHANNEL_TYPES.map((ct) => (
                  <SelectItem key={ct} value={ct}>
                    {ct}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {ch.type === "email" ? (
              <Input
                className="flex-1"
                placeholder="recipient@example.com"
                value={ch.config["to"] ?? ""}
                onChange={(e) =>
                  updateChannelConfig(idx, "to", e.target.value)
                }
              />
            ) : (
              <Input
                className="flex-1"
                placeholder="https://hooks.example.com/..."
                value={ch.config["url"] ?? ""}
                onChange={(e) =>
                  updateChannelConfig(idx, "url", e.target.value)
                }
              />
            )}

            <Button
              variant="ghost"
              size="sm"
              onClick={() => removeChannel(idx)}
              className="text-ink-tertiary"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            setChannels((prev) => [...prev, emptyChannel()])
          }
          className="text-ink-subtle hover:text-ink"
        >
          <Plus className="mr-2 h-4 w-4" /> {t("notifications.addChannel")}
        </Button>
      </div>

      {/* Template */}
      <div className="space-y-2">
        <Label>{t("notifications.template")}</Label>
        <Textarea
          rows={3}
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          placeholder="Run {{run_id}} finished with status {{status}}"
        />
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="outline" size="sm" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button size="sm" onClick={handleSave} disabled={isPending || !name.trim() || channels.length === 0}>
          <Save className="mr-2 h-4 w-4" />
          {isPending ? t("common.loading") : t("common.save")}
        </Button>
      </div>
    </div>
  );
}
