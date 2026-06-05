import { Copy, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ApiTokenResponse } from "../../../types/api";
import { Button } from "../../ui/button";
import { Input } from "../../ui/input";

export function CreatedTokenBanner({
  token,
  onCopy,
  onDismiss,
}: {
  token: ApiTokenResponse;
  onCopy: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="rounded-xl border border-status-passed/30 bg-status-passed/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-ink">
            {t("settings.tokens.createdTitle")}
          </h2>
          <p className="text-xs text-ink-subtle">
            {t("settings.tokens.visibleOnce")}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onDismiss}
          aria-label={t("settings.tokens.dismissToken")}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <Input
          readOnly
          value={token.token ?? ""}
          className="font-mono text-xs"
          aria-label={t("settings.tokens.createdValue")}
        />
        <Button variant="outline" onClick={onCopy}>
          <Copy className="mr-2 h-4 w-4" />
          {t("settings.tokens.copy")}
        </Button>
      </div>
    </div>
  );
}
