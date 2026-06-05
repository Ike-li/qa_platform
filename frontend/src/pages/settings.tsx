import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ApiTokenTable } from "../components/settings/api-tokens/api-token-table";
import { CreateApiTokenDialog } from "../components/settings/api-tokens/create-api-token-dialog";
import { CreatedTokenBanner } from "../components/settings/api-tokens/created-token-banner";
import { Button } from "../components/ui/button";
import {
  useApiTokens,
  useRevokeApiToken,
} from "../hooks/use-api-tokens";
import { usePageTitle } from "../hooks/use-page-title";
import type { ApiTokenListItem, ApiTokenResponse } from "../types/api";
import { API_TOKENS_PER_PAGE, errorDetail } from "../components/settings/api-tokens/utils";

export default function Settings() {
  const { t, i18n } = useTranslation();
  usePageTitle(t("settings.title"));
  const [page, setPage] = useState(1);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createdToken, setCreatedToken] = useState<ApiTokenResponse | null>(null);
  const [revokingTokenId, setRevokingTokenId] = useState<string | null>(null);
  const { data, isLoading, isError, refetch } = useApiTokens({
    page,
    per_page: API_TOKENS_PER_PAGE,
  });
  const { mutateAsync: revokeToken } = useRevokeApiToken();

  const handleRetry = () => {
    if (page === 1) {
      void refetch();
      return;
    }
    setPage(1);
  };

  const copyCreatedToken = async () => {
    if (!createdToken?.token) return;
    try {
      await navigator.clipboard.writeText(createdToken.token);
      toast.success(t("settings.tokens.toast.copied"));
    } catch {
      toast.error(t("settings.tokens.toast.copyFailed"));
    }
  };

  const handleRevoke = async (token: ApiTokenListItem) => {
    setRevokingTokenId(token.token_id);
    try {
      await revokeToken(token.token_id);
      toast.success(t("settings.tokens.toast.revoked"));
    } catch (error) {
      toast.error(errorDetail(error, t("settings.tokens.toast.revokeFailed")));
    } finally {
      setRevokingTokenId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("settings.title")}
          </h1>
          <p className="text-sm text-ink-subtle">
            {t("settings.tokens.subtitle")}
          </p>
        </div>
        <Button className="w-full sm:w-auto" onClick={() => setIsCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t("settings.tokens.create")}
        </Button>
      </div>

      <CreateApiTokenDialog
        open={isCreateOpen}
        onOpenChange={setIsCreateOpen}
        onCreated={setCreatedToken}
      />

      {createdToken?.token && (
        <CreatedTokenBanner
          token={createdToken}
          onCopy={copyCreatedToken}
          onDismiss={() => setCreatedToken(null)}
        />
      )}

      {isError && (
        <div className="rounded-xl border border-status-failed/20 bg-status-failed/5 p-6 text-center">
          <p className="text-sm text-status-failed">
            {t("settings.tokens.failedToLoad")}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={handleRetry}
          >
            {t("common.retry")}
          </Button>
        </div>
      )}

      {!isError && (
        <ApiTokenTable
          data={data}
          isLoading={isLoading}
          locale={i18n.language}
          revokingTokenId={revokingTokenId}
          onRevoke={(token) => void handleRevoke(token)}
        />
      )}

      {data && data.total > data.per_page && (
        <div className="flex items-center justify-between px-2">
          <p className="text-xs text-ink-tertiary">
            {t("settings.tokens.showingOf", {
              count: data.data.length,
              total: data.total,
            })}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              {t("common.previous")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page * data.per_page >= data.total}
              onClick={() => setPage((current) => current + 1)}
            >
              {t("common.next")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
