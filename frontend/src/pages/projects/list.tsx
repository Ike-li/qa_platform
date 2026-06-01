import { useState, useDeferredValue } from "react";
import { Link } from "react-router-dom";
import { Search, Plus, GitBranch, ExternalLink, Clock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useProjects } from "../../hooks/use-projects";
import { Button } from "../../components/ui/button";
import { RelativeTime } from "../../components/relative-time";
import { Skeleton } from "../../components/ui/skeleton";
import { EmptyState } from "../../components/ui/empty-state";
import { CreateProjectModal } from "../../components/projects/create-project-modal";
import { cn } from "../../lib/utils";
import { usePageTitle } from "../../hooks/use-page-title";

export default function Projects() {
  const { t } = useTranslation();
  usePageTitle(t('projects.title'));
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { data, isLoading, isError, refetch } = useProjects({ search: deferredSearch });

  const handleRetry = () => {
    if (search.trim() || deferredSearch.trim()) {
      setSearch("");
      return;
    }
    void refetch();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t('projects.title')}</h1>
          <p className="text-sm text-ink-subtle">{t('projects.subtitle')}</p>
        </div>
        <Button className="w-full sm:w-auto" onClick={() => setIsModalOpen(true)}>
          <Plus className="mr-2 h-4 w-4" /> {t('projects.newProject')}
        </Button>
      </div>

      <CreateProjectModal open={isModalOpen} onOpenChange={setIsModalOpen} />

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
        <input
          type="text"
          placeholder={t('projects.searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-md border border-hairline bg-surface-1 py-2 pl-10 pr-4 text-sm placeholder:text-ink-tertiary focus:border-primary-focus focus:outline-none focus:ring-1 focus:ring-primary-focus transition-colors"
        />
      </div>

      {isError ? (
        <div className="rounded-xl border border-status-failed/20 bg-status-failed/5 p-6 text-center">
          <p className="text-sm text-status-failed">{t('projects.failedToLoad')}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={handleRetry}>{t('common.retry')}</Button>
        </div>
      ) : isLoading ? (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="rounded-xl border border-hairline bg-surface-1 p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1 space-y-3">
                  <Skeleton className="h-5 w-2/3" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-4/5" />
                </div>
                <Skeleton className="h-5 w-16 rounded-full" />
              </div>
              <div className="mt-8 space-y-4">
                <Skeleton className="h-4 w-4/5" />
                <div className="flex items-center justify-between border-t border-hairline pt-3">
                  <Skeleton className="h-3 w-28" />
                  <Skeleton className="h-3 w-16" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : data?.data.length === 0 ? (
        <EmptyState
          icon={<Search className="h-6 w-6" />}
          title={t('projects.noProjectsFound')}
          description={t('projects.noProjectsDescription')}
          action={{
            label: search ? t('projects.clearSearch') : t('projects.newProject'),
            onClick: () => search ? setSearch("") : setIsModalOpen(true)
          }}
        />
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {data?.data.map((project) => (
            <Link
              key={project.id}
              to={`/projects/${project.id}`}
              className="group flex flex-col gap-4 rounded-xl border border-hairline bg-surface-1 p-6 transition-all hover:border-hairline-strong hover:bg-surface-2"
            >
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <h3 className="truncate text-lg font-medium text-ink group-hover:text-primary transition-colors">{project.name}</h3>
                  <p className="mt-1 line-clamp-2 text-sm text-ink-subtle">{project.description || t('projects.noDescription')}</p>
                </div>
                <span className={cn(
                  "shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider border",
                  project.status === "active" ? "bg-status-passed/10 text-status-passed border-status-passed/20" : "bg-ink-tertiary/10 text-ink-tertiary border-ink-tertiary/20"
                )}>
                  {t('projectStatus.' + project.status)}
                </span>
              </div>

              <div className="mt-auto space-y-3">
                <div className="flex items-center gap-2 text-xs text-ink-muted">
                  <GitBranch className="h-3 w-3" />
                  <span className="truncate">{project.git_url}</span>
                  <ExternalLink className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>

                <div className="flex items-center justify-between border-t border-hairline pt-3 text-xs text-ink-tertiary">
                  <div className="flex items-center gap-1.5">
                    <Clock className="h-3 w-3" />
                    <span>{t('projects.updated')} <RelativeTime date={project.updated_at} /></span>
                  </div>
                  <span className="font-mono">{project.slug}</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
