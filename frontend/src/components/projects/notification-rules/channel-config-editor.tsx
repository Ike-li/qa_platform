import { useTranslation } from "react-i18next";

import type { NotificationChannel } from "../../../types/api";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../ui/select";
import {
  CHANNEL_MSGTYPES,
  channelConfigText,
  parseList,
} from "./helpers";

export function ChannelConfigEditor({
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
            value={
              channelConfigText(channel, "to_addresses") ||
              channelConfigText(channel, "to")
            }
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
