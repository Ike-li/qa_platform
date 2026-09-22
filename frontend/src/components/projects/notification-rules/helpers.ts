import type {
  NotificationChannel,
  NotificationCondition,
  NotificationConditionExpression,
  NotificationConditionGroup,
  NotificationConditionInputExpression,
  NotificationRule,
} from "../../../types/api";

export const CONDITION_FIELDS: NotificationCondition["field"][] = [
  "status",
  "pass_rate",
  "failed",
  "consecutive_failures",
  "new_failed",
  "recovered",
];

export const CONDITION_OPS: NotificationCondition["operator"][] = [
  "eq",
  "ne",
  "lt",
  "gt",
  "lte",
  "gte",
];

export const CHANNEL_TYPES: NotificationChannel["type"][] = [
  "email",
  "webhook",
  "dingtalk",
  "wecom",
];

export const CHANNEL_MSGTYPES = ["text", "markdown"];
export const CONDITION_MODES = ["all", "any"] as const;
export type ConditionMode = (typeof CONDITION_MODES)[number];

export const CHANNEL_LABELS: Record<NotificationChannel["type"], string> = {
  dingtalk: "DingTalk",
  email: "Email",
  webhook: "Webhook",
  wecom: "WeCom",
};

export function emptyCondition(): NotificationCondition {
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

export function conditionModeFromRule(
  conditions: NotificationRule["conditions"] | undefined
): ConditionMode {
  const group = conditions?.find(isConditionGroup);
  return group && "any" in group ? "any" : "all";
}

export function conditionRowsFromRule(
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

export function serializeConditionsForSave(
  mode: ConditionMode,
  conditions: NotificationCondition[]
): NotificationConditionInputExpression[] {
  if (conditions.length === 0) return [];
  return mode === "any" ? [{ any: conditions }] : conditions;
}

export function defaultChannelConfig(
  type: NotificationChannel["type"]
): NotificationChannel["config"] {
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

export function emptyChannel(
  type: NotificationChannel["type"] = "email"
): NotificationChannel {
  return { type, config: defaultChannelConfig(type), template: null };
}

export function channelTypeOptions(
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

export function nextAvailableChannelType(
  channels: NotificationChannel[]
): NotificationChannel["type"] | null {
  return CHANNEL_TYPES.find(
    (type) => !channels.some((channel) => channel.type === type)
  ) ?? null;
}

export function channelConfigText(channel: NotificationChannel, key: string): string {
  const value = channel.config[key];
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return value ?? "";
}

export function parseList(value: string): string[] {
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

export function normalizeChannelForSave(
  channel: NotificationChannel
): NotificationChannel {
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
