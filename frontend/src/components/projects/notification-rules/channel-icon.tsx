import { Mail, MessageSquare, Send, Webhook } from "lucide-react";

import type { NotificationChannel } from "../../../types/api";

export function ChannelIcon({
  type,
  className = "h-3 w-3",
}: {
  type: NotificationChannel["type"];
  className?: string;
}) {
  if (type === "email") return <Mail className={className} />;
  if (type === "webhook") return <Webhook className={className} />;
  if (type === "dingtalk") return <Send className={className} />;
  return <MessageSquare className={className} />;
}
