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
  const { data, isLoading } = useRuns({ per_page: 20 });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Recent Runs</h1>
          <p className="text-sm text-ink-subtle">Monitor automation execution across all projects</p>
        </div>
      </div>

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
                  <td colSpan={7} className="px-6 py-4"><Skeleton className="h-4 w-full" /></td>
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
      
      {data && data.total > data.per_page && (
        <div className="flex items-center justify-between px-2">
          <p className="text-xs text-ink-tertiary">Showing {data.data.length} of {data.total} runs</p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={data.page === 1}>Previous</Button>
            <Button variant="outline" size="sm" disabled={data.page * data.per_page >= data.total}>Next</Button>
          </div>
        </div>
      )}
    </div>
  );
}
