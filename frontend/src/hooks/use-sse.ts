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
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const eventSourceRef = useRef<EventSource | null>(null);
  const lastEventIdRef = useRef<string | null>(null);
  const retryCount = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectingRef = useRef(false); // Track in-progress connection attempts
  const maxRetries = 5;

  const cleanup = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    connectingRef.current = false; // Reset connection state
  }, []);

  useEffect(() => {
    lastEventIdRef.current = null;
    queueMicrotask(() => setLastEventId(null));
  }, [url]);

  useEffect(() => {
    if (!enabled) {
      cleanup();
      queueMicrotask(() => setStatus('disconnected'));
      return;
    }

    const connect = async () => {
      // Prevent multiple concurrent connection attempts
      if (connectingRef.current) {
        return;
      }
      if (eventSourceRef.current && eventSourceRef.current.readyState !== EventSource.CLOSED) {
        return;
      }

      connectingRef.current = true;
      setStatus('connecting');

      let ticket: string;
      try {
        ticket = await fetchSSETicket();
      } catch {
        connectingRef.current = false;
        setStatus('disconnected');
        if (retryCount.current < maxRetries) {
          retryCount.current += 1;
          const timeout = Math.min(1000 * Math.pow(2, retryCount.current), 30000);
          retryTimerRef.current = setTimeout(connect, timeout);
        }
        return;
      }

      const query = new URLSearchParams({ ticket });
      if (lastEventIdRef.current) {
        query.set('last_event_id', lastEventIdRef.current);
      }
      const sseUrl = `${url}${url.includes('?') ? '&' : '?'}${query.toString()}`;
      const es = new EventSource(sseUrl);
      eventSourceRef.current = es;

      es.onopen = () => {
        connectingRef.current = false;
        setStatus('connected');
        setError(null);
        retryCount.current = 0;
      };

      const handleMessage = (event: MessageEvent) => {
        const nextLastEventId = event.lastEventId || null;
        lastEventIdRef.current = nextLastEventId;
        setLastEventId(nextLastEventId);
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
        connectingRef.current = false;
        setError(e);
        setStatus('disconnected');
        es.close();
        eventSourceRef.current = null;

        if (retryCount.current < maxRetries) {
          retryCount.current += 1;
          const timeout = Math.min(1000 * Math.pow(2, retryCount.current), 30000);
          retryTimerRef.current = setTimeout(connect, timeout);
        }
      };
    };

    connect();

    return cleanup;
  }, [url, enabled, cleanup]);

  return { data, status, error, lastEventId };
}
