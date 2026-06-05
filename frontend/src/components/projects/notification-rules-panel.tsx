import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useNotificationRules } from "../../hooks/use-notifications";
import type { NotificationRule } from "../../types/api";
import { Button } from "../ui/button";
import { RuleCard } from "./notification-rules/rule-card";
import { RuleForm } from "./notification-rules/rule-form";

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
          key={editingRule?.id ?? "create"}
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
