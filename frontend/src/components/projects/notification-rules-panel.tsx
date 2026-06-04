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
  MessageSquare,
  Send,
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
  NotificationConditionGroup,
  NotificationConditionInputExpression,
  NotificationConditionExpression,
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
  "consecutive_failures",
];

const CONDITION_OPS: NotificationCondition["operator"][] = [
  "eq",
  "ne",
  "lt",
  "gt",
  "lte",
  "gte",
];

const CHANNEL_TYPES: NotificationChannel["type"][] = [
  "email",
  "webhook",
  "dingtalk",
  "wecom",
];
const CHANNEL_MSGTYPES = ["text", "markdown"];
const CONDITION_MODES = ["all", "any"] as const;
type ConditionMode = (typeof CONDITION_MODES)[number];

const CHANNEL_LABELS: Record<NotificationChannel["type"], string> = {
  dingtalk: "DingTalk",
  email: "Email",
  webhook: "Webhook",
  wecom: "WeCom",
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function emptyCondition(): NotificationCondition {
  return { field: "status", operator: "eq", value: "" };
}

function isConditionLeaf(
  condition: NotificationConditionExpression
): condition is NotificationCondition {
  return "field" in condition && "operator" in condition && "value" in condition;
}

function isConditionGroup(
  condition: NotificationConditionExpression
): condition is NotificationConditionGroup {
  return "all" in condition || "any" in condition;
}

function conditionModeFromRule(
  conditions: NotificationRule["conditions"] | undefined
): ConditionMode {
  const group = conditions?.find(isConditionGroup);
  return group && "any" in group ? "any" : "all";
}

function conditionRowsFromRule(
  conditions: NotificationRule["conditions"] | undefined
): NotificationCondition[] {
  if (!conditions || conditions.length === 0) return [emptyCondition()];
  const group = conditions.find(isConditionGroup);
  if (group) {
    const rows = "any" in group ? group.any : group.all;
    const leafRows = rows?.filter(isConditionLeaf) ?? [];
    return leafRows.length > 0 ? leafRows : [emptyCondition()];
  }
  const rows = conditions.filter(isConditionLeaf);
  return rows.length > 0 ? rows : [emptyCondition()];
}

function serializeConditionsForSave(
  mode: ConditionMode,
  conditions: NotificationCondition[]
): NotificationConditionInputExpression[] {
  if (conditions.length === 0) return [];
  return mode === "any" ? [{ any: conditions }] : conditions;
}

function defaultChannelConfig(type: NotificationChannel["type"]): NotificationChannel["config"] {
  switch (type) {
    case "email":
      return { smtp_port: "587", to_addresses: [] as string[] };
    case "webhook":
      return { method: "POST" };
    case "dingtalk":
    case "wecom":
      return { msgtype: "text" };
  }
}

function emptyChannel(type: NotificationChannel["type"] = "email"): NotificationChannel {
  return { type, config: defaultChannelConfig(type), template: null };
}

function channelTypeOptions(
  channels: NotificationChannel[],
  index: number
): NotificationChannel["type"][] {
  const usedByOtherChannels = new Set(
    channels
      .filter((_, channelIndex) => channelIndex !== index)
      .map((channel) => channel.type)
  );
  return CHANNEL_TYPES.filter(
    (type) => type === channels[index]?.type || !usedByOtherChannels.has(type)
  );
}

function nextAvailableChannelType(
  channels: NotificationChannel[]
): NotificationChannel["type"] | null {
  return CHANNEL_TYPES.find(
    (type) => !channels.some((channel) => channel.type === type)
  ) ?? null;
}

function channelConfigText(channel: NotificationChannel, key: string): string {
  const value = channel.config[key];
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return value ?? "";
}

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function compactConfig(config: NotificationChannel["config"]) {
  return Object.fromEntries(
    Object.entries(config).filter(([, value]) => {
      if (Array.isArray(value)) {
        return value.length > 0;
      }
      return value.trim() !== "";
    })
  );
}

function normalizeChannelForSave(channel: NotificationChannel): NotificationChannel {
  const config = { ...channel.config };
  if (channel.type === "email") {
    const recipients = parseList(
      channelConfigText(channel, "to_addresses") || channelConfigText(channel, "to")
    );
    delete config.to;
    config.to_addresses = recipients;
    config.smtp_port = config.smtp_port || "587";
  }
  if (channel.type === "webhook") {
    config.method = config.method || "POST";
  }
  if (channel.type === "dingtalk" || channel.type === "wecom") {
    config.msgtype = config.msgtype || "text";
  }

  const normalized: NotificationChannel = {
    type: channel.type,
    config: compactConfig(config),
  };
  const template = channel.template?.trim();
  if (template) {
    normalized.template = template;
  }
  return normalized;
}

function ChannelIcon({ type, className = "h-3 w-3" }: { type: NotificationChannel["type"]; className?: string }) {
  if (type === "email") return <Mail className={className} />;
  if (type === "webhook") return <Webhook className={className} />;
  if (type === "dingtalk") return <Send className={className} />;
  return <MessageSquare className={className} />;
}

function ChannelConfigEditor({
  channel,
  index,
  updateChannelConfig,
}: {
  channel: NotificationChannel;
  index: number;
  updateChannelConfig: (
    index: number,
    key: string,
    value: NotificationChannel["config"][string]
  ) => void;
}) {
  const { t } = useTranslation();
  const update = (key: string, value: NotificationChannel["config"][string]) =>
    updateChannelConfig(index, key, value);

  if (channel.type === "email") {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <Label>{t("notifications.channel.smtpHost")}</Label>
          <Input
            value={channelConfigText(channel, "smtp_host")}
            onChange={(e) => update("smtp_host", e.target.value)}
            placeholder="smtp.example.com"
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.smtpPort")}</Label>
          <Input
            value={channelConfigText(channel, "smtp_port")}
            onChange={(e) => update("smtp_port", e.target.value)}
            placeholder="587"
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.fromAddress")}</Label>
          <Input
            value={channelConfigText(channel, "from_address")}
            onChange={(e) => update("from_address", e.target.value)}
            placeholder="qa@example.com"
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.toAddresses")}</Label>
          <Input
            value={channelConfigText(channel, "to_addresses") || channelConfigText(channel, "to")}
            onChange={(e) => update("to_addresses", parseList(e.target.value))}
            placeholder="owner@example.com, qa@example.com"
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.smtpUser")}</Label>
          <Input
            value={channelConfigText(channel, "smtp_user")}
            onChange={(e) => update("smtp_user", e.target.value)}
            placeholder="smtp-user"
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.smtpPassword")}</Label>
          <Input
            type="password"
            value={channelConfigText(channel, "smtp_password")}
            onChange={(e) => update("smtp_password", e.target.value)}
          />
        </div>
        <div className="space-y-2 md:col-span-2">
          <Label>{t("notifications.channel.subject")}</Label>
          <Input
            value={channelConfigText(channel, "subject")}
            onChange={(e) => update("subject", e.target.value)}
            placeholder="QA Platform Notification"
          />
        </div>
      </div>
    );
  }

  if (channel.type === "webhook") {
    return (
      <div className="grid gap-3 md:grid-cols-[1fr_8rem]">
        <div className="space-y-2">
          <Label>{t("notifications.channel.webhookUrl")}</Label>
          <Input
            value={channelConfigText(channel, "url")}
            onChange={(e) => update("url", e.target.value)}
            placeholder="https://hooks.example.com/..."
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.method")}</Label>
          <Input
            value={channelConfigText(channel, "method")}
            onChange={(e) => update("method", e.target.value.toUpperCase())}
            placeholder="POST"
          />
        </div>
      </div>
    );
  }

  if (channel.type === "dingtalk") {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <Label>{t("notifications.channel.accessToken")}</Label>
          <Input
            type="password"
            value={channelConfigText(channel, "access_token")}
            onChange={(e) => update("access_token", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.secret")}</Label>
          <Input
            type="password"
            value={channelConfigText(channel, "secret")}
            onChange={(e) => update("secret", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.msgtype")}</Label>
          <Select
            value={channelConfigText(channel, "msgtype") || "text"}
            onValueChange={(value) => update("msgtype", value)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CHANNEL_MSGTYPES.map((msgtype) => (
                <SelectItem key={msgtype} value={msgtype}>
                  {msgtype}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>{t("notifications.channel.title")}</Label>
          <Input
            value={channelConfigText(channel, "title")}
            onChange={(e) => update("title", e.target.value)}
            placeholder="QA Platform Notification"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="space-y-2">
        <Label>{t("notifications.channel.webhookKey")}</Label>
        <Input
          type="password"
          value={channelConfigText(channel, "webhook_key")}
          onChange={(e) => update("webhook_key", e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label>{t("notifications.channel.msgtype")}</Label>
        <Select
          value={channelConfigText(channel, "msgtype") || "text"}
          onValueChange={(value) => update("msgtype", value)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CHANNEL_MSGTYPES.map((msgtype) => (
              <SelectItem key={msgtype} value={msgtype}>
                {msgtype}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
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
            type="button"
            size="sm"
            variant="ghost"
            className="text-ink-tertiary hover:text-ink"
            onClick={onEdit}
            aria-label={t("notifications.editRuleAria", { name: rule.name })}
            title={t("notifications.editRuleAria", { name: rule.name })}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="text-ink-tertiary hover:text-status-failed"
                aria-label={t("notifications.deleteRuleAria", {
                  name: rule.name,
                })}
                title={t("notifications.deleteRuleAria", {
                  name: rule.name,
                })}
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
                <ChannelIcon type={ch.type} />
                {CHANNEL_LABELS[ch.type]}
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
  const [conditionMode, setConditionMode] = useState<ConditionMode>(
    conditionModeFromRule(rule?.conditions)
  );
  const [conditions, setConditions] = useState<NotificationCondition[]>(
    conditionRowsFromRule(rule?.conditions)
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
  const hasDuplicateChannelTypes =
    new Set(channels.map((channel) => channel.type)).size !== channels.length;
  const nextChannelType = nextAvailableChannelType(channels);

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
    value: NotificationChannel["config"][string]
  ) => {
    setChannels((prev) =>
      prev.map((c, i) =>
        i === index
          ? { ...c, config: { ...c.config, [key]: value } }
          : c
      )
    );
  };
  const updateChannelTemplate = (index: number, value: string) => {
    updateChannel(index, { template: value });
  };
  const removeChannel = (index: number) =>
    setChannels((prev) => (
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)
    ));
  const addChannel = () => {
    setChannels((prev) => {
      const type = nextAvailableChannelType(prev);
      return type ? [...prev, emptyChannel(type)] : prev;
    });
  };

  /* ---- submit ---- */
  const handleSave = async () => {
    if (!name.trim()) return;
    if (channels.length === 0) {
      toast.error(t("notifications.channelsRequired"));
      return;
    }
    if (hasDuplicateChannelTypes) {
      toast.error(t("notifications.duplicateChannels"));
      return;
    }
    try {
      const payload = {
        name: name.trim(),
        enabled,
        conditions: serializeConditionsForSave(conditionMode, conditions),
        channels: channels.map(normalizeChannelForSave),
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
        <div className="flex items-center justify-between gap-3">
          <Label>{t("notifications.conditions")}</Label>
          <Select
            value={conditionMode}
            onValueChange={(value) => setConditionMode(value as ConditionMode)}
          >
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CONDITION_MODES.map((mode) => (
                <SelectItem key={mode} value={mode}>
                  {t(`notifications.conditionMode.${mode}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
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
                    {t(`notifications.condition.field.${f}`)}
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
          <div
            key={idx}
            className="space-y-3 border-t border-hairline pt-3 first:border-t-0 first:pt-0"
          >
            <div className="flex items-center gap-2">
              <Select
                value={ch.type}
                onValueChange={(v) =>
                  updateChannel(idx, {
                    type: v as NotificationChannel["type"],
                    config: defaultChannelConfig(v as NotificationChannel["type"]),
                    template: null,
                  })
                }
              >
                <SelectTrigger className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {channelTypeOptions(channels, idx).map((ct) => (
                    <SelectItem key={ct} value={ct}>
                      {CHANNEL_LABELS[ct]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <span className="inline-flex items-center gap-1 text-sm text-ink-muted">
                <ChannelIcon type={ch.type} className="h-4 w-4" />
                {CHANNEL_LABELS[ch.type]}
              </span>

              <Button
                variant="ghost"
                size="sm"
                onClick={() => removeChannel(idx)}
                className="ml-auto text-ink-tertiary"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <ChannelConfigEditor
              channel={ch}
              index={idx}
              updateChannelConfig={updateChannelConfig}
            />

            <div className="space-y-2">
              <Label>{t("notifications.channelTemplate")}</Label>
              <Textarea
                rows={2}
                value={ch.template ?? ""}
                onChange={(e) => updateChannelTemplate(idx, e.target.value)}
                placeholder="Run {{run_id}} finished with status {{status}}"
              />
            </div>
          </div>
        ))}
        <Button
          variant="ghost"
          size="sm"
          onClick={addChannel}
          disabled={!nextChannelType}
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
        <Button
          size="sm"
          onClick={handleSave}
          disabled={
            isPending ||
            !name.trim() ||
            channels.length === 0 ||
            hasDuplicateChannelTypes
          }
        >
          <Save className="mr-2 h-4 w-4" />
          {isPending ? t("common.loading") : t("common.save")}
        </Button>
      </div>
    </div>
  );
}
