import { useEffect, useRef, useState, useCallback } from 'react';
import { getAccessToken } from '../lib/api';

export function useSSE<T = unknown>(url: string, enabled: boolean = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Event | null>(null);
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryCount = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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
  }, []);

  useEffect(() => {
    if (!enabled) {
      cleanup();
      setStatus('disconnected');
      return;
    }

    const connect = () => {
      if (!eventSourceRef.current || eventSourceRef.current.readyState === EventSource.CLOSED) {
        setStatus('connecting');
        const token = getAccessToken();
        const sseUrl = `${url}${url.includes('?') ? '&' : '?'}token=${token}`;

        const es = new EventSource(sseUrl);
        eventSourceRef.current = es;

        es.onopen = () => {
          setStatus('connected');
          setError(null);
          retryCount.current = 0;
        };

        es.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data) as T;
            setData(parsed);
          } catch {
            setData(event.data as T);
          }
        };

        es.onerror = (e) => {
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
      }
    };

    connect();

    return cleanup;
  }, [url, enabled, cleanup]);

  return { data, status, error };
}
