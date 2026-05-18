import { useTranslation } from "react-i18next";
import { Globe } from "lucide-react";
import { cn } from "../lib/utils";

export function LanguageSwitcher({ isOpen }: { isOpen: boolean }) {
  const { i18n } = useTranslation();
  const nextLang = i18n.language === "zh-CN" ? "en" : "zh-CN";
  const label = i18n.language === "zh-CN" ? "English" : "中文";

  return (
    <button
      onClick={() => i18n.changeLanguage(nextLang)}
      className={cn(
        "flex w-full items-center rounded-md px-3 py-2 text-sm font-medium text-ink-subtle hover:bg-surface-1 hover:text-ink transition-colors",
        !isOpen && "justify-center px-0"
      )}
    >
      <Globe className="h-4 w-4 shrink-0" />
      {isOpen && <span className="ml-3 truncate">{label}</span>}
    </button>
  );
}
