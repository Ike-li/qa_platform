import { useEffect, useRef, useState, useCallback } from 'react';
import api from '../lib/api';

async function fetchSSETicket(): Promise<string> {
  const { data } = await api.post<{ ticket: string }>('/auth/sse-ticket');
  return data.ticket;
}

export function useSSE<T = unknown>(url: string, enabled: boolean = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Event | null>(null);
  const [lastEventId, setLastEventId] = useState<string | null>(null);
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'polling'>('connecting');
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryCount = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const maxRetries = 5;

  const cleanup = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    setStatus('polling');
    const poll = async () => {
      try {
        const { data: polled } = await api.get<T>(url);
        setData(polled);
      } catch {
        // Polling failure is non-fatal; next interval will retry.
      }
    };
    poll();
    pollTimerRef.current = setInterval(poll, 5000);
  }, [url]);

  useEffect(() => {
    if (!enabled) {
      cleanup();
      queueMicrotask(() => setStatus('disconnected'));
      return;
    }

    const connect = async () => {
      if (eventSourceRef.current && eventSourceRef.current.readyState !== EventSource.CLOSED) {
        return;
      }

      retryCount.current = 0;
      setStatus('connecting');

      let ticket: string;
      try {
        ticket = await fetchSSETicket();
      } catch {
        setStatus('disconnected');
        if (retryCount.current < maxRetries) {
          retryCount.current += 1;
          const timeout = Math.min(1000 * Math.pow(2, retryCount.current), 30000);
          retryTimerRef.current = setTimeout(connect, timeout);
        } else {
          startPolling();
        }
        return;
      }

      const sseUrl = `${url}${url.includes('?') ? '&' : '?'}ticket=${encodeURIComponent(ticket)}`;
      const es = new EventSource(sseUrl);
      eventSourceRef.current = es;

      es.onopen = () => {
        setStatus('connected');
        setError(null);
        retryCount.current = 0;
      };

      const handleMessage = (event: MessageEvent) => {
        setLastEventId(event.lastEventId || null);
        try {
          const parsed = JSON.parse(event.data) as T;
          setData(parsed);
        } catch {
          setData(event.data as T);
        }
      };

      es.onmessage = handleMessage;
      es.addEventListener('log', handleMessage);
      es.addEventListener('status_change', handleMessage);
      es.addEventListener('done', handleMessage);

      es.onerror = (e) => {
        setError(e);
        setStatus('disconnected');
        es.close();
        eventSourceRef.current = null;

        if (retryCount.current < maxRetries) {
          retryCount.current += 1;
          const timeout = Math.min(1000 * Math.pow(2, retryCount.current), 30000);
          retryTimerRef.current = setTimeout(connect, timeout);
        } else {
          startPolling();
        }
      };
    };

    connect();

    return cleanup;
  }, [url, enabled, cleanup, startPolling]);

  return { data, status, error, lastEventId };
}
