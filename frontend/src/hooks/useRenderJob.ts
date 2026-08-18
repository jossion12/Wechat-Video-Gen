import { useCallback, useEffect, useRef, useState } from 'react';
import { getJob, subscribeJobEvents } from '../api';
import type { JobStatusResponse, RenderJobEvent } from '../types';

/**
 * 跟踪单个渲染任务：先 GET 初始状态，再通过 SSE 订阅增量事件。
 * jobId 为 null 时不做任何请求；切换 jobId 时自动重置。
 */
export function useRenderJob(jobId: string | null) {
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  const stop = useCallback(() => {
    if (unsubscribeRef.current) {
      unsubscribeRef.current();
      unsubscribeRef.current = null;
    }
  }, []);

  const applyEvent = useCallback((ev: RenderJobEvent) => {
    setJob((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        status: ev.status,
        progress: ev.progress ?? prev.progress,
        output_url: ev.output_url ?? prev.output_url,
        error: ev.error ?? prev.error,
      };
    });
  }, []);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setError(null);
      setLoading(false);
      return undefined;
    }

    let disposed = false;
    setLoading(true);
    setError(null);

    getJob(jobId)
      .then((initial) => {
        if (disposed) return;
        setJob(initial);
        // 任务已终态时无需再订阅
        if (initial.status === 'done' || initial.status === 'failed') {
          setLoading(false);
          return;
        }
        unsubscribeRef.current = subscribeJobEvents(jobId, (ev) => {
          if (disposed) return;
          applyEvent(ev);
          if (ev.status === 'done' || ev.status === 'failed') {
            setLoading(false);
          }
        });
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });

    return () => {
      disposed = true;
      stop();
    };
  }, [jobId, applyEvent, stop]);

  return { job, error, loading };
}
