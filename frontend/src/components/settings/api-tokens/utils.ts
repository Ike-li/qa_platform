export const API_TOKENS_PER_PAGE = 20;

export function parseScopes(value: string) {
  const scopes = value
    .split(",")
    .map((scope) => scope.trim())
    .filter(Boolean);
  return scopes.length > 0 ? scopes : ["*"];
}

export function formatDate(value: string | null, locale: string) {
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

export function errorDetail(error: unknown, fallback: string) {
  const axiosError = error as { response?: { data?: { detail?: string } } };
  return axiosError.response?.data?.detail || fallback;
}

export function scopeLabel(scopes: string[]) {
  return scopes.length > 0 ? scopes.join(", ") : "*";
}

export function tokenStatusLabel(
  isRevoked: boolean,
  t: (key: string) => string
) {
  return isRevoked
    ? t("settings.tokens.status.revoked")
    : t("settings.tokens.status.active");
}
