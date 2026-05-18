import { useEffect } from "react";
import i18n from "../i18n";

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} | ${i18n.t("common.appName")}`;
  }, [title]);
}
