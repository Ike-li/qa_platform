import { Link } from "react-router-dom";
import { Home } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "../components/ui/button";
import { usePageTitle } from "../hooks/use-page-title";

export default function NotFound() {
  const { t } = useTranslation();
  usePageTitle("404");

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center text-center">
      <p className="text-sm font-medium text-primary">404</p>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-ink">{t('errors.pageNotFoundTitle')}</h1>
      <p className="mt-2 max-w-sm text-sm text-ink-subtle">
        {t('errors.pageNotFoundDescription')}
      </p>
      <Button asChild className="mt-6">
        <Link to="/projects">
          <Home className="mr-2 h-4 w-4" />
          {t('errors.goHome')}
        </Link>
      </Button>
    </div>
  );
}
