import { useState } from "react";
import { Share2, Copy, Check, Trash2, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import {
  useCreateShareToken,
  useShareTokens,
  useRevokeShareToken,
  type ShareToken,
} from "../../hooks/use-report-shares";
import { RelativeTime } from "../relative-time";

interface ShareReportDialogProps {
  runId: string;
  trigger?: React.ReactNode;
}

export function ShareReportDialog({ runId, trigger }: ShareReportDialogProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [expiresInDays, setExpiresInDays] = useState(7);
  const [maxAccessCount, setMaxAccessCount] = useState<number | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  const { data: tokens = [], isLoading: isLoadingTokens } = useShareTokens(runId);
  const { mutateAsync: createToken, isPending: isCreating } = useCreateShareToken(runId);
  const { mutateAsync: revokeToken } = useRevokeShareToken(runId);

  const handleCreateToken = async () => {
    try {
      const result = await createToken({
        expires_in_days: expiresInDays,
        max_access_count: maxAccessCount,
      });

      // Auto-copy the new URL
      const fullUrl = `${window.location.origin}${result.share_url}`;
      await navigator.clipboard.writeText(fullUrl);
      setCopiedToken(result.id);
      setTimeout(() => setCopiedToken(null), 2000);

      toast.success(t("runs.share.created"));
    } catch {
      toast.error(t("runs.share.createFailed"));
    }
  };

  const handleCopyUrl = async (token: ShareToken) => {
    const fullUrl = `${window.location.origin}${token.share_url}`;
    await navigator.clipboard.writeText(fullUrl);
    setCopiedToken(token.id);
    setTimeout(() => setCopiedToken(null), 2000);
    toast.success(t("runs.share.copied"));
  };

  const handleRevokeToken = async (tokenId: string) => {
    try {
      await revokeToken(tokenId);
      toast.success(t("runs.share.revoked"));
    } catch {
      toast.error(t("runs.share.revokeFailed"));
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm">
            <Share2 className="mr-2 h-4 w-4" />
            {t("runs.share.button")}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("runs.share.title")}</DialogTitle>
          <DialogDescription>{t("runs.share.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Create new share link */}
          <div className="space-y-4 rounded-lg border border-hairline bg-surface-0 p-4">
            <h3 className="text-sm font-medium">{t("runs.share.createNew")}</h3>

            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="expires-in">{t("runs.share.expiresIn")}</Label>
                <Input
                  id="expires-in"
                  type="number"
                  min="1"
                  max="90"
                  value={expiresInDays}
                  onChange={(e) => setExpiresInDays(parseInt(e.target.value) || 7)}
                  placeholder="7"
                />
                <p className="text-xs text-ink-muted">
                  {t("runs.share.expiresInHint")}
                </p>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="max-access">{t("runs.share.maxAccess")}</Label>
                <Input
                  id="max-access"
                  type="number"
                  min="1"
                  value={maxAccessCount ?? ""}
                  onChange={(e) =>
                    setMaxAccessCount(e.target.value ? parseInt(e.target.value) : null)
                  }
                  placeholder={t("runs.share.unlimited")}
                />
                <p className="text-xs text-ink-muted">
                  {t("runs.share.maxAccessHint")}
                </p>
              </div>
            </div>

            <Button
              onClick={handleCreateToken}
              disabled={isCreating}
              className="w-full"
            >
              {isCreating ? t("runs.share.creating") : t("runs.share.create")}
            </Button>
          </div>

          {/* Existing share links */}
          <div className="space-y-4">
            <h3 className="text-sm font-medium">{t("runs.share.existing")}</h3>

            {isLoadingTokens ? (
              <div className="text-sm text-ink-muted">{t("common.loading")}</div>
            ) : tokens.length === 0 ? (
              <div className="text-sm text-ink-muted">{t("runs.share.noTokens")}</div>
            ) : (
              <div className="space-y-3">
                {tokens.map((token: ShareToken) => (
                  <div
                    key={token.id}
                    className="flex items-start gap-3 rounded-lg border border-hairline bg-surface-0 p-4"
                  >
                    <div className="flex-1 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">
                            {t("runs.share.tokenLabel")}
                          </span>
                          {token.is_expired && (
                            <span className="text-xs rounded bg-status-failed/10 px-2 py-0.5 text-status-failed">
                              {t("runs.share.expired")}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => window.open(
                              `${window.location.origin}${token.share_url}`,
                              "_blank"
                            )}
                          >
                            <ExternalLink className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleCopyUrl(token)}
                          >
                            {copiedToken === token.id ? (
                              <Check className="h-4 w-4 text-status-passed" />
                            ) : (
                              <Copy className="h-4 w-4" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRevokeToken(token.id)}
                          >
                            <Trash2 className="h-4 w-4 text-status-failed" />
                          </Button>
                        </div>
                      </div>

                      <div className="text-xs text-ink-muted space-y-1">
                        <div>
                          {t("runs.share.accessCount")}: {token.access_count}
                          {token.max_access_count && ` / ${token.max_access_count}`}
                        </div>
                        <div>
                          {t("runs.share.expires")}:{" "}
                          <RelativeTime date={token.expires_at} />
                        </div>
                        <div>
                          {t("runs.share.createdBy")}: {token.created_by}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
