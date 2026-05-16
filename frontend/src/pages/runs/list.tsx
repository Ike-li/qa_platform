import { useState } from "react";
import { Link } from "react-router-dom";
import {
  GitBranch,
  Clock,
  User,
  ArrowRight
} from "lucide-react";
import { useRuns } from "../../hooks/use-runs";
import { RunStatusBadge } from "../../components/run-status-badge";
import { DurationDisplay } from "../../components/duration-display";
import { RelativeTime } from "../../components/relative-time";
import { Skeleton } from "../../components/ui/skeleton";
import { EmptyState } from "../../components/ui/empty-state";
import { Button } from "../../components/ui/button";
import { usePageTitle } from "../../hooks/use-page-title";

export default function Runs() {
  usePageTitle("Runs");
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useRuns({ per_page: 20, page });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Recent Runs</h1>
          <p className="text-sm text-ink-subtle">Monitor automation execution across all projects</p>
        </div>
      </div>

      {isError && (
        <div className="rounded-xl border border-status-failed/20 bg-status-failed/5 p-6 text-center">
          <p className="text-sm text-status-failed">Failed to load runs.</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => setPage(1)}>Retry</Button>
        </div>
      )}

      {!isError && (
      <div className="rounded-xl border border-hairline bg-surface-1 overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-hairline bg-surface-2/50 text-ink-muted">
              <th className="px-6 py-3 font-medium">Status</th>
              <th className="px-6 py-3 font-medium">Pipeline</th>
              <th className="px-6 py-3 font-medium">Branch</th>
              <th className="px-6 py-3 font-medium">Triggered By</th>
              <th className="px-6 py-3 font-medium">Duration</th>
              <th className="px-6 py-3 font-medium">Started</th>
              <th className="px-6 py-3 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {isLoading ? (
              [1, 2, 3, 4, 5].map(i => (
                <tr key={i}>
                  <td className="px-6 py-4"><Skeleton className="h-5 w-20 rounded-full" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-36" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-24" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-28" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-20" /></td>
                  <td className="px-6 py-4"><Skeleton className="h-4 w-24" /></td>
                  <td className="px-6 py-4 text-right">
                    <Skeleton className="ml-auto h-8 w-20" />
                  </td>
                </tr>
              ))
            ) : data?.data.length === 0 ? (
              <tr>
                <td colSpan={7} className="p-0">
                  <EmptyState 
                    title="No runs found"
                    description="Trigger a pipeline in a project to see runs here."
                    className="border-0 rounded-none rounded-b-xl"
                  />
                </td>
              </tr>
            ) : (
              data?.data.map(run => (
                <tr key={run.id} className="group hover:bg-surface-2/50 transition-colors">
                  <td className="px-6 py-4">
                    <RunStatusBadge status={run.status} />
                  </td>
                  <td className="px-6 py-4 font-medium text-ink">
                    <Link to={`/runs/${run.id}`} className="hover:text-primary transition-colors">
                      {run.pipeline_name}
                    </Link>
                  </td>
                  <td className="px-6 py-4 text-ink-muted">
                    <div className="flex items-center gap-1.5">
                      <GitBranch className="h-3.5 w-3.5" />
                      <span>{run.branch}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-ink-muted">
                    <div className="flex items-center gap-1.5">
                      <User className="h-3.5 w-3.5" />
                      <span>{run.triggered_by}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-ink-muted">
                    <div className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5" />
                      <DurationDisplay seconds={run.duration_seconds} />
                    </div>
                  </td>
                  <td className="px-6 py-4 text-ink-tertiary">
                    <RelativeTime date={run.created_at} />
                  </td>
                  <td className="px-6 py-4 text-right">
                    <Button variant="ghost" size="sm" asChild>
                      <Link to={`/runs/${run.id}`}>
                        Details <ArrowRight className="ml-2 h-3 w-3" />
                      </Link>
                    </Button>
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
          <p className="text-xs text-ink-tertiary">Showing {data.data.length} of {data.total} runs</p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
            <Button variant="outline" size="sm" disabled={page * data.per_page >= data.total} onClick={() => setPage(p => p + 1)}>Next</Button>
          </div>
        </div>
      )}
    </div>
  );
}
