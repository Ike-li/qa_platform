import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useCreateApiToken } from "../../../hooks/use-api-tokens";
import type { ApiTokenResponse } from "../../../types/api";
import { Button } from "../../ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../ui/dialog";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import { errorDetail, parseScopes } from "./utils";

export function CreateApiTokenDialog({
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
    if (
      !Number.isInteger(parsedExpiresDays) ||
      parsedExpiresDays < 1 ||
      parsedExpiresDays > 365
    ) {
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
