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
} from "../../ui/alert-dialog";
import { Bell, BellOff, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useDeleteNotificationRule } from "../../../hooks/use-notifications";
import type { NotificationRule } from "../../../types/api";
import { Button } from "../../ui/button";
import { ChannelIcon } from "./channel-icon";
import { CHANNEL_LABELS } from "./helpers";

export function RuleCard({
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
            {rule.conditions.length}{" "}
            {t("notifications.conditionsCount", {
              count: rule.conditions.length,
            })}
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
