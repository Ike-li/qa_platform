import { type FormEvent, useState } from "react";
import { Copy, KeyRound, Plus, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { EmptyState } from "../components/ui/empty-state";
import { Skeleton } from "../components/ui/skeleton";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { RelativeTime } from "../components/relative-time";
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
} from "../components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  useApiTokens,
  useCreateApiToken,
  useRevokeApiToken,
} from "../hooks/use-api-tokens";
import { usePageTitle } from "../hooks/use-page-title";
import type { ApiTokenListItem, ApiTokenResponse } from "../types/api";

const PER_PAGE = 20;

function parseScopes(value: string) {
  const scopes = value
    .split(",")
    .map((scope) => scope.trim())
    .filter(Boolean);
  return scopes.length > 0 ? scopes : ["*"];
}

function formatDate(value: string | null, locale: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function errorDetail(error: unknown, fallback: string) {
  const axiosError = error as { response?: { data?: { detail?: string } } };
  return axiosError.response?.data?.detail || fallback;
}

function scopeLabel(scopes: string[]) {
  return scopes.length > 0 ? scopes.join(", ") : "*";
}

function tokenStatusLabel(isRevoked: boolean, t: (key: string) => string) {
  return isRevoked
    ? t("settings.tokens.status.revoked")
    : t("settings.tokens.status.active");
}

export default function Settings() {
  const { t, i18n } = useTranslation();
  usePageTitle(t("settings.title"));
  const [page, setPage] = useState(1);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createdToken, setCreatedToken] = useState<ApiTokenResponse | null>(null);
  const [revokingTokenId, setRevokingTokenId] = useState<string | null>(null);
  const { data, isLoading, isError, refetch } = useApiTokens({
    page,
    per_page: PER_PAGE,
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
              onClick={() => setCreatedToken(null)}
              aria-label={t("settings.tokens.dismissToken")}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <Input
              readOnly
              value={createdToken.token}
              className="font-mono text-xs"
              aria-label={t("settings.tokens.createdValue")}
            />
            <Button variant="outline" onClick={copyCreatedToken}>
              <Copy className="mr-2 h-4 w-4" />
              {t("settings.tokens.copy")}
            </Button>
          </div>
        </div>
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
                      {formatDate(token.expires_at, i18n.language)}
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
                              onClick={() => handleRevoke(token)}
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

function CreateApiTokenDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (token: ApiTokenResponse) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState("*");
  const [expiresDays, setExpiresDays] = useState("90");
  const { mutateAsync: createToken, isPending } = useCreateApiToken();

  const reset = () => {
    setName("");
    setScopes("*");
    setExpiresDays("90");
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsedExpiresDays = Number(expiresDays);
    if (!Number.isInteger(parsedExpiresDays) || parsedExpiresDays < 1 || parsedExpiresDays > 365) {
      toast.error(t("settings.tokens.validation.expiresDays"));
      return;
    }

    try {
      const created = await createToken({
        name: name.trim(),
        scopes: parseScopes(scopes),
        expires_days: parsedExpiresDays,
      });
      onCreated(created);
      toast.success(t("settings.tokens.toast.created"));
      onOpenChange(false);
      reset();
    } catch (error) {
      toast.error(errorDetail(error, t("settings.tokens.toast.createFailed")));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("settings.tokens.create")}</DialogTitle>
          <DialogDescription>
            {t("settings.tokens.createDescription")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="api-token-name">
              {t("settings.tokens.form.name")}
            </Label>
            <Input
              id="api-token-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("settings.tokens.form.namePlaceholder")}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="api-token-scopes">
              {t("settings.tokens.form.scopes")}
            </Label>
            <Input
              id="api-token-scopes"
              value={scopes}
              onChange={(event) => setScopes(event.target.value)}
              placeholder={t("settings.tokens.form.scopesPlaceholder")}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="api-token-expires-days">
              {t("settings.tokens.form.expiresDays")}
            </Label>
            <Input
              id="api-token-expires-days"
              type="number"
              min={1}
              max={365}
              value={expiresDays}
              onChange={(event) => setExpiresDays(event.target.value)}
              required
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={isPending || !name.trim()}>
              {isPending
                ? t("settings.tokens.creating")
                : t("settings.tokens.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
