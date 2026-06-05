import { Plus, Save, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  useCreateNotificationRule,
  useUpdateNotificationRule,
} from "../../../hooks/use-notifications";
import type {
  NotificationChannel,
  NotificationCondition,
  NotificationRule,
} from "../../../types/api";
import { Button } from "../../ui/button";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../ui/select";
import { Switch } from "../../ui/switch";
import { Textarea } from "../../ui/textarea";
import { ChannelConfigEditor } from "./channel-config-editor";
import { ChannelIcon } from "./channel-icon";
import {
  CHANNEL_LABELS,
  CONDITION_FIELDS,
  CONDITION_MODES,
  CONDITION_OPS,
  type ConditionMode,
  channelTypeOptions,
  conditionModeFromRule,
  conditionRowsFromRule,
  defaultChannelConfig,
  emptyChannel,
  emptyCondition,
  nextAvailableChannelType,
  normalizeChannelForSave,
  serializeConditionsForSave,
} from "./helpers";

export function RuleForm({
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
        i === index ? { ...c, config: { ...c.config, [key]: value } } : c
      )
    );
  };
  const updateChannelTemplate = (index: number, value: string) => {
    updateChannel(index, { template: value });
  };
  const removeChannel = (index: number) =>
    setChannels((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)
    );
  const addChannel = () => {
    setChannels((prev) => {
      const type = nextAvailableChannelType(prev);
      return type ? [...prev, emptyChannel(type)] : prev;
    });
  };

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
          onClick={() => setConditions((prev) => [...prev, emptyCondition()])}
          className="text-ink-subtle hover:text-ink"
        >
          <Plus className="mr-2 h-4 w-4" /> {t("notifications.addCondition")}
        </Button>
      </div>

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
                    config: defaultChannelConfig(
                      v as NotificationChannel["type"]
                    ),
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

      <div className="space-y-2">
        <Label>{t("notifications.template")}</Label>
        <Textarea
          rows={3}
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          placeholder="Run {{run_id}} finished with status {{status}}"
        />
      </div>

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
