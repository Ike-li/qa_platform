import { KeyRound, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { RelativeTime } from "../../relative-time";
import type { ApiTokenListItem, PaginatedResponse } from "../../../types/api";
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
import { Button } from "../../ui/button";
import { EmptyState } from "../../ui/empty-state";
import { Skeleton } from "../../ui/skeleton";
import { formatDate, scopeLabel, tokenStatusLabel } from "./utils";

export function ApiTokenTable({
  data,
  isLoading,
  locale,
  revokingTokenId,
  onRevoke,
}: {
  data: PaginatedResponse<ApiTokenListItem> | undefined;
  isLoading: boolean;
  locale: string;
  revokingTokenId: string | null;
  onRevoke: (token: ApiTokenListItem) => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="overflow-x-auto rounded-xl border border-hairline bg-surface-1">
      <table className="w-full min-w-[860px] text-left text-sm">
        <thead>
          <tr className="border-b border-hairline bg-surface-2/50 text-ink-muted">
            <th className="px-6 py-3 font-medium">
              {t("settings.tokens.table.name")}
            </th>
            <th className="px-6 py-3 font-medium">
              {t("settings.tokens.table.scopes")}
            </th>
            <th className="px-6 py-3 font-medium">
              {t("settings.tokens.table.created")}
            </th>
            <th className="px-6 py-3 font-medium">
              {t("settings.tokens.table.lastUsed")}
            </th>
            <th className="px-6 py-3 font-medium">
              {t("settings.tokens.table.expires")}
            </th>
            <th className="px-6 py-3 font-medium">
              {t("settings.tokens.table.status")}
            </th>
            <th className="px-6 py-3 text-right font-medium">
              {t("settings.tokens.table.action")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline">
          {isLoading ? (
            [1, 2, 3].map((item) => (
              <tr key={item}>
                <td className="px-6 py-4">
                  <Skeleton className="h-4 w-40" />
                </td>
                <td className="px-6 py-4">
                  <Skeleton className="h-5 w-28 rounded-full" />
                </td>
                <td className="px-6 py-4">
                  <Skeleton className="h-4 w-28" />
                </td>
                <td className="px-6 py-4">
                  <Skeleton className="h-4 w-24" />
                </td>
                <td className="px-6 py-4">
                  <Skeleton className="h-4 w-28" />
                </td>
                <td className="px-6 py-4">
                  <Skeleton className="h-5 w-16 rounded-full" />
                </td>
                <td className="px-6 py-4 text-right">
                  <Skeleton className="ml-auto h-8 w-8" />
                </td>
              </tr>
            ))
          ) : data?.data.length === 0 ? (
            <tr>
              <td colSpan={7} className="p-0">
                <EmptyState
                  icon={<KeyRound className="h-6 w-6" />}
                  title={t("settings.tokens.empty")}
                  description={t("settings.tokens.emptyDescription")}
                  className="border-0 rounded-none rounded-b-xl"
                />
              </td>
            </tr>
          ) : (
            data?.data.map((token) => (
              <tr
                key={token.token_id}
                className="hover:bg-surface-2/50 transition-colors"
              >
                <td className="px-6 py-4 font-medium text-ink">
                  {token.name}
                </td>
                <td className="px-6 py-4">
                  <span className="inline-flex max-w-[18rem] items-center rounded-full border border-hairline bg-canvas px-2 py-0.5 font-mono text-xs text-ink-muted">
                    <span className="truncate">{scopeLabel(token.scopes)}</span>
                  </span>
                </td>
                <td className="px-6 py-4 text-ink-tertiary">
                  <RelativeTime date={token.created_at} />
                </td>
                <td className="px-6 py-4 text-ink-tertiary">
                  {token.last_used_at ? (
                    <RelativeTime date={token.last_used_at} />
                  ) : (
                    "-"
                  )}
                </td>
                <td className="px-6 py-4 text-ink-muted">
                  {formatDate(token.expires_at, locale)}
                </td>
                <td className="px-6 py-4">
                  <span
                    className={
                      token.is_revoked
                        ? "inline-flex rounded-full border border-hairline bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-tertiary"
                        : "inline-flex rounded-full border border-status-passed/30 bg-status-passed/5 px-2 py-0.5 text-xs font-medium text-status-passed"
                    }
                  >
                    {tokenStatusLabel(token.is_revoked, t)}
                  </span>
                </td>
                <td className="px-6 py-4 text-right">
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-ink-tertiary hover:text-status-failed"
                        disabled={token.is_revoked}
                        aria-label={t("settings.tokens.revokeAria", {
                          name: token.name,
                        })}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>
                          {t("settings.tokens.revokeTitle")}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                          {t("settings.tokens.revokeDescription", {
                            name: token.name,
                          })}
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>
                          {t("common.cancel")}
                        </AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => onRevoke(token)}
                          disabled={revokingTokenId === token.token_id}
                          className="bg-status-failed hover:bg-status-failed/90"
                        >
                          {revokingTokenId === token.token_id
                            ? t("settings.tokens.revoking")
                            : t("settings.tokens.revoke")}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
