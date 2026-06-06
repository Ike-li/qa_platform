import { useEffect, useRef, useState, useMemo, useCallback, type ComponentType } from 'react';
import { Terminal, Search, Pause, Play, ChevronDown } from 'lucide-react';
import AnsiToReactImport from 'ansi-to-react';
import DOMPurify from 'dompurify';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useTranslation } from 'react-i18next';
import { useSSE } from '../../hooks/use-sse';
import { useArchivedRunLogs } from '../../hooks/use-runs';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { cn } from '../../lib/utils';
import i18n from '../../i18n';

type AnsiToReactComponent = ComponentType<{ children?: string }>;
const AnsiToReact = (
  typeof AnsiToReactImport === 'function'
    ? AnsiToReactImport
    : (AnsiToReactImport as unknown as { default: AnsiToReactComponent }).default
) as AnsiToReactComponent;

interface LogMessage {
  timestamp?: string;
  level?: string;
  message: string;
}

// Maximum number of log entries to keep in memory to prevent memory exhaustion
// with long-running tests. Older entries are dropped when limit is reached.
const MAX_LOG_ENTRIES = 10000;

function sanitizeLogMessage(message: string): string {
  return DOMPurify.sanitize(message, {
    ALLOWED_TAGS: [],
    ALLOWED_ATTR: [],
  });
}

export function LogViewer({ runId, archivedEnabled = false }: { runId: string; archivedEnabled?: boolean }) {
  const { t } = useTranslation();
  const [logs, setLogs] = useState<LogMessage[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [search, setSearch] = useState('');

  const scrollRef = useRef<HTMLDivElement>(null);
  const seenEventIdsRef = useRef<Set<string>>(new Set());

  const { data, status, lastEventId } = useSSE<LogMessage | string | Record<string, unknown>>(
    `/api/v1/runs/${runId}/logs`,
    !archivedEnabled,
  );
  const archivedLogsQuery = useArchivedRunLogs(runId, archivedEnabled);

  useEffect(() => {
    setLogs([]);
    seenEventIdsRef.current.clear();
  }, [runId]);

  useEffect(() => {
    if (data) {
      if (lastEventId) {
        if (seenEventIdsRef.current.has(lastEventId)) {
          return;
        }
        seenEventIdsRef.current.add(lastEventId);
      }

      const logEntry: LogMessage | null = typeof data === 'string'
        ? { message: data }
        : typeof data.message === 'string'
          ? {
              timestamp: typeof data.timestamp === 'string' ? data.timestamp : undefined,
              level: typeof data.level === 'string' ? data.level : undefined,
              message: data.message,
            }
          : null;
      if (!logEntry) return;
      setLogs((prev) => {
        const updated = [...prev, logEntry];
        // Keep only the most recent MAX_LOG_ENTRIES to prevent memory exhaustion
        if (updated.length > MAX_LOG_ENTRIES) {
          return updated.slice(updated.length - MAX_LOG_ENTRIES);
        }
        return updated;
      });
    }
  }, [data, lastEventId]);

  const archivedLogs = useMemo<LogMessage[]>(() => {
    if (!archivedEnabled || !archivedLogsQuery.data?.data.length) return [];
    return archivedLogsQuery.data.data.map((entry) => ({
      level: entry.stream === 'stderr' ? 'error' : 'info',
      message: entry.line,
    }));
  }, [archivedEnabled, archivedLogsQuery.data]);

  const sourceLogs = archivedLogs.length > 0 ? archivedLogs : logs;
  const usingArchivedLogs = archivedLogs.length > 0;

  const filteredLogs = useMemo(() => {
    if (!search) return sourceLogs;
    const lowerSearch = search.toLowerCase();
    return sourceLogs.filter(log => log.message.toLowerCase().includes(lowerSearch));
  }, [sourceLogs, search]);

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual exposes imperative methods used directly below.
  const virtualizer = useVirtualizer({
    count: filteredLogs.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  useEffect(() => {
    if (autoScroll && filteredLogs.length > 0) {
      virtualizer.scrollToIndex(filteredLogs.length - 1, { align: 'end' });
    }
  }, [filteredLogs.length, autoScroll, virtualizer]);

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isAtBottom);
  }, []);

  const emptyMessage = archivedEnabled && archivedLogsQuery.isLoading
    ? t("common.loading")
    : archivedEnabled && archivedLogsQuery.isError
      ? t("logs.archiveUnavailable")
      : t("logs.waitingForLogs");
  const statusLabel = usingArchivedLogs ? t("logs.archived") : t(`logs.${status}`);

  return (
    <div className="relative flex flex-col h-[600px] rounded-lg border border-hairline bg-surface-1 overflow-hidden">
      {/* Log Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-hairline bg-surface-2/50">
        <div className="flex items-center gap-3">
          <Terminal className="h-4 w-4 text-ink-subtle" />
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-ink">{t("logs.title")}</span>
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface-3">
              <span className={cn(
                "h-2 w-2 rounded-full",
                usingArchivedLogs || status === 'connected' ? "bg-status-passed" :
                status === 'connecting' ? "bg-status-running animate-pulse" :
                "bg-status-failed"
              )} />
              <span className="text-xs text-ink-muted">{statusLabel}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative w-48">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-tertiary" />
            <Input
              placeholder={t("logs.searchPlaceholder")}
              value={search}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
              className="h-8 pl-8 text-xs bg-surface-3 border-hairline"
            />
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-ink-subtle hover:text-ink"
            onClick={() => setAutoScroll(!autoScroll)}
            aria-label={autoScroll ? t("logs.pauseAutoScroll") : t("logs.resumeAutoScroll")}
            title={autoScroll ? t("logs.pauseAutoScroll") : t("logs.resumeAutoScroll")}
          >
            {autoScroll ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {/* Log Body - Virtualized */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-4 font-mono text-[13px] leading-relaxed text-ink-muted bg-surface-1"
      >
        {filteredLogs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-ink-tertiary space-y-2">
            <Terminal className="h-8 w-8 opacity-20" />
            <p>{emptyMessage}</p>
          </div>
        ) : (
          <div
            style={{ height: `${virtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}
          >
            {virtualizer.getVirtualItems().map((virtualItem) => {
              const log = filteredLogs[virtualItem.index];
              return (
                <div
                  key={virtualItem.index}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualItem.start}px)`,
                  }}
                  className="flex hover:bg-surface-2/30 px-1 -mx-1 rounded"
                >
                  {log.timestamp && (
                    <span className="text-ink-tertiary mr-3 shrink-0 select-none">
                      [{new Date(log.timestamp).toLocaleTimeString(i18n.language)}]
                    </span>
                  )}
                  <span className="whitespace-pre-wrap break-all">
                    <AnsiToReact>{sanitizeLogMessage(log.message)}</AnsiToReact>
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Auto-scroll resume overlay */}
      {!autoScroll && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2">
          <Button
            variant="secondary"
            size="sm"
            className="shadow-lg border-hairline-strong rounded-full"
            onClick={() => {
              setAutoScroll(true);
              virtualizer.scrollToIndex(filteredLogs.length - 1, { align: 'end' });
            }}
          >
            <ChevronDown className="mr-1.5 h-4 w-4" />
            {t("logs.resumeAutoScroll")}
          </Button>
        </div>
      )}
    </div>
  );
}
