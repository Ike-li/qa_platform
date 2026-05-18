import { useTranslation } from "react-i18next";

export function DurationDisplay({ seconds }: { seconds: number | null | undefined }) {
  const { t } = useTranslation();
  if (seconds === null || seconds === undefined) return <span>-</span>;

  if (seconds < 60) {
    return <span>{t("time.seconds", { count: Math.round(seconds) })}</span>;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);

  return (
    <span>
      {t("time.minutes", { count: minutes })} {t("time.seconds", { count: remainingSeconds })}
    </span>
  );
}
