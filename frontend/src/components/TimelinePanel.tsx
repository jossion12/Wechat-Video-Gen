import { useEffect, useMemo, useRef, useState } from 'react';
import {
  getTimeline,
  // ⚠️ Qwen3-TTS(已注释,DISABLED / DEPRECATED)⚠️
  // getTtsBySourceJob, submitTtsFromJob,
  subscribeJobEvents,
} from '../api';
import type {
  // ⚠️ Qwen3-TTS(已注释,DISABLED / DEPRECATED)⚠️
  // JobStatus 仅用于 TtsSection 内 Extract<JobStatus, 'queued' | 'running'>;
  // 当前版本(回退 Qwen3-TTS)TtsSection 已注释,这里保留 import 以便恢复时一行解注即可。
  JobStatus,
  RenderJobEvent,
  TimelineDocument,
  TimelineEntry,
  TimelineEventType,
} from '../types';

interface TimelinePanelProps {
  jobId: string;
  /** 返回主视图(Step 5)回调 — 用户在表格页点「返回」时调用 */
  onBack: () => void;
  /** 该任务的时间码 JSON 下载链接 — 由 ProgressPanel 传入,可空 */
  timelineUrl: string | null;
}

const KIND_LABELS: Record<string, string> = {
  disclaimer: '声明卡',
  intro: '开场特效',
  text: '文字',
  image: '图片',
  video: '视频',
  emoji: '表情',
  sys: '系统消息',
  timestamp: '时间戳',
};

// 过滤类型比 TimelineEventType 更宽 —— 还要覆盖消息子类型(text/image/video/emoji),
// 表格按这些子类型筛比按 timeline.type(msg/sys/timestamp) 更符合用户直觉。
type FilterValue = TimelineEventType | 'text' | 'image' | 'video' | 'emoji' | 'all';

const FILTER_OPTIONS: { value: FilterValue; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'text', label: '文字' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
  { value: 'emoji', label: '表情' },
  { value: 'sys', label: '系统' },
  { value: 'timestamp', label: '时间戳' },
  { value: 'disclaimer', label: '声明卡' },
  { value: 'intro', label: '开场' },
];

function formatMs(ms: number): string {
  if (ms < 0) ms = 0;
  const totalSec = ms / 1000;
  const sec = Math.floor(totalSec);
  const mm = Math.floor(sec / 60);
  const ss = sec % 60;
  const mss = Math.floor(ms % 1000);
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}.${String(mss).padStart(3, '0')}`;
}

function summarizeText(entry: TimelineEntry): string {
  if (entry.summary) return entry.summary;
  if (entry.kind === 'disclaimer') return '本对话由 AI 生成,仅供创意表达';
  if (entry.kind === 'intro') return entry.text || '';
  return entry.text || `[${KIND_LABELS[entry.kind] ?? entry.kind}]`;
}

function formatDurationSec(sec: number | null): string {
  if (sec === null || !Number.isFinite(sec) || sec < 0) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}分${s}秒`;
}

/**
 * 时间码查看页:
 *   顶部:任务 id + 总时长 + 下载按钮 + 返回按钮
 *   中部:类型过滤
 *   主体:表格列出每条事件(出现 / 消失 / 持续时长),带简易时间轴预览条
 *   底部:TTS 语音合成卡片(独立子组件 TtsSection)
 *
 * 数据来源:`GET /api/jobs/{job_id}/timeline` 返回的 TimelineDocument。
 */
export function TimelinePanel({ jobId, onBack, timelineUrl }: TimelinePanelProps) {
  const [doc, setDoc] = useState<TimelineDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<FilterValue>('all');

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    getTimeline(jobId)
      .then((d) => {
        if (disposed) return;
        setDoc(d);
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setError(err instanceof Error ? err.message : '加载时间码失败');
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [jobId]);

  const filteredEntries = useMemo(() => {
    if (!doc) return [];
    if (filter === 'all') return doc.entries;
    return doc.entries.filter((e) => e.kind === filter);
  }, [doc, filter]);

  const totalMs = doc?.total_duration_ms ?? 0;

  return (
    <section className="card timeline-card">
      <div className="timeline-head">
        <div className="timeline-head-left">
          <h2 className="card-title">时间码</h2>
          <span className="timeline-job-id">job: {jobId}</span>
        </div>
        <div className="timeline-head-right">
          {timelineUrl && (
            <a
              className="btn btn-sm"
              href={timelineUrl}
              download={`${jobId}.timeline.json`}
            >
              下载 JSON
            </a>
          )}
          <button type="button" className="btn btn-sm" onClick={onBack}>
            返回预览
          </button>
        </div>
      </div>

      {loading && <p className="timeline-loading">正在加载时间码…</p>}
      {error && <div className="error-text">{error}</div>}

      {doc && (
        <>
          <div className="timeline-summary">
            <span className="timeline-stat">
              <span className="timeline-stat-label">总时长</span>
              <span className="timeline-stat-value">{formatMs(totalMs)}</span>
            </span>
            <span className="timeline-stat">
              <span className="timeline-stat-label">条目数</span>
              <span className="timeline-stat-value">{doc.entries.length}</span>
            </span>
            <span className="timeline-stat">
              <span className="timeline-stat-label">过滤后</span>
              <span className="timeline-stat-value">{filteredEntries.length}</span>
            </span>
          </div>

          <div className="timeline-filter">
            <span className="timeline-filter-label">按类型过滤:</span>
            <div className="timeline-filter-group">
              {FILTER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`btn btn-sm timeline-filter-btn${filter === opt.value ? ' timeline-filter-btn--active' : ''}`}
                  onClick={() => setFilter(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {filteredEntries.length === 0 ? (
            <p className="timeline-empty">当前过滤下没有条目。</p>
          ) : (
            <>
              {/* 时间轴预览:水平条上画每条事件的 appeared→disappeared 区间。
                  用百分比定位,与视频播放器解耦,不依赖像素。 */}
              <div className="timeline-track" aria-label="时间轴预览">
                {filteredEntries.map((e) => {
                  const left = totalMs > 0 ? (e.appeared_at / totalMs) * 100 : 0;
                  const width = totalMs > 0
                    ? Math.max(0.5, ((e.disappeared_at - e.appeared_at) / totalMs) * 100)
                    : 0;
                  return (
                    <div
                      key={`track-${e.id}`}
                      className={`timeline-track-bar timeline-track-bar--${e.kind}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      title={`${KIND_LABELS[e.kind] ?? e.kind} · ${formatMs(e.appeared_at)}–${formatMs(e.disappeared_at)}`}
                    />
                  );
                })}
              </div>

              <table className="timeline-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>类型</th>
                    <th>发送者</th>
                    <th>摘要</th>
                    <th>出现</th>
                    <th>消失</th>
                    <th>持续</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEntries.map((e, idx) => (
                    <tr key={e.id}>
                      <td>{idx + 1}</td>
                      <td>
                        <span className={`timeline-kind-badge timeline-kind-badge--${e.kind}`}>
                          {KIND_LABELS[e.kind] ?? e.kind}
                        </span>
                      </td>
                      <td>{e.sender_name || (e.sender_id === '__system__' ? '—' : e.sender_id)}</td>
                      <td className="timeline-summary-cell">{summarizeText(e)}</td>
                      <td>{formatMs(e.appeared_at)}</td>
                      <td>{formatMs(e.disappeared_at)}</td>
                      <td>{formatMs(e.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {/* TTS 语音合成卡片 —— 与表格同卡内,虚线分隔。doc 存在(render 已 done)
              时才有意义;doc 为 null(loading/error)时不渲染,避免误导用户。
              ⚠️ Qwen3-TTS(已注释,DISABLED / DEPRECATED)⚠️
              <TtsSection renderJobId={jobId} />
              当前版本(回退 Qwen3-TTS)时间码页底部 TTS 卡片已注释,
              见下方 TtsSection 组件 / handleTtsEvent 块注释。 */}
        </>
      )}
    </section>
  );
}

// ---------- TTS 语音合成卡片 ----------
// ⚠️ Qwen3-TTS(已注释,DISABLED / DEPRECATED)⚠️
// 下方 TtsSection / TtsSectionProps / TtsPhase / handleTtsEvent 已重命名为
// _DISABLED_QWEN3_TTS_ 前缀以避免被引用,代码原封保留供恢复时去掉 _DISABLED_ 前缀即可。
// /api/tts/from-job 与 /api/tts/by-source 端点已在 backend/app/main.py 注释;
// 前端不再渲染 TTS 卡片,这些函数仅留作「回滚后再次启用」时的代码存档。

interface _DISABLED_QWEN3_TTS_TtsSectionProps {
  /** render 任务的 jobId —— by-source 反查 + from-job 入参都用这个 */
  renderJobId: string;
}

type _DISABLED_QWEN3_TTS_TtsPhase =
  | { phase: 'loading' }
  | { phase: 'idle' }
  | {
      phase: 'running';
      ttsJobId: string;
      progress: number;
      status: Extract<JobStatus, 'queued' | 'running'>;
    }
  | {
      phase: 'done';
      ttsJobId: string;
      failedCount: number;
      audioUrl: string | null;
      durationSec: number | null;
    }
  | {
      phase: 'failed';
      ttsJobId: string | null;
      error: string;
    };

/**
 * 时间码页底部的「TTS 语音合成」子模块:
 *   - mount 时拉 /api/tts/by-source/{jobId},决定 idle / running / done / failed;
 *   - 点「生成语音」调 /api/tts/from-job 拿到 tts_job_id,然后 SSE 推进;
 *   - done 时再读 audio metadata 拿 duration 显示;
 *   - failed 时显示 reason + 「重新生成」按钮(回到 idle,再点重提交)。
 *
 * 状态机走 useState<TtsPhase> 联合类型,避免分散多个 useState 同步问题。
 * SSE 取消函数存 ref,组件 unmount 时调一次 abort。
 */
function _DISABLED_QWEN3_TTS_TtsSection({ renderJobId }: _DISABLED_QWEN3_TTS_TtsSectionProps) {
  const [state, setState] = useState<_DISABLED_QWEN3_TTS_TtsPhase>({ phase: 'loading' });
  const [submitting, setSubmitting] = useState(false);
  const sseUnsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let disposed = false;
    setState({ phase: 'loading' });

    getTtsBySourceJob(renderJobId)
      .then((t) => {
        if (disposed) return;
        if (!t) {
          setState({ phase: 'idle' });
          return;
        }
        if (t.status === 'done') {
          setState({
            phase: 'done',
            ttsJobId: t.tts_job_id,
            failedCount: t.metadata_json?.failed_segments?.length ?? 0,
            audioUrl: t.output_url,
            durationSec: null,
          });
          return;
        }
        if (t.status === 'failed') {
          setState({
            phase: 'failed',
            ttsJobId: t.tts_job_id,
            error: t.error ?? '语音合成失败',
          });
          return;
        }
        // queued / running → 启动 SSE 接续推进
        setState({
          phase: 'running',
          ttsJobId: t.tts_job_id,
          progress: t.progress,
          status: t.status,
        });
        sseUnsubRef.current = subscribeJobEvents(t.tts_job_id, (ev) => {
          if (disposed) return;
          _DISABLED_QWEN3_TTS_handleTtsEvent(ev, setState);
        });
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setState({
          phase: 'failed',
          ttsJobId: null,
          error: err instanceof Error ? err.message : '查询语音任务失败',
        });
      });

    return () => {
      disposed = true;
      sseUnsubRef.current?.();
      sseUnsubRef.current = null;
    };
  }, [renderJobId]);

  // done 后用 Audio 元素读 metadata 拿真实时长(SSE 事件不带 duration)。
  // 只在 audioUrl 变化时跑一次;loadedmetadata 触发后用 prev guard 避免重复 setState。
  const audioUrl = state.phase === 'done' ? state.audioUrl : null;
  useEffect(() => {
    if (!audioUrl) return;
    const audio = new Audio();
    let cancelled = false;
    audio.preload = 'metadata';
    audio.src = audioUrl;
    audio.addEventListener('loadedmetadata', () => {
      if (cancelled) return;
      const sec = Number.isFinite(audio.duration) ? audio.duration : null;
      setState((prev) =>
        prev.phase === 'done' && prev.durationSec === null
          ? { ...prev, durationSec: sec }
          : prev,
      );
    });
    return () => {
      cancelled = true;
      audio.src = '';
    };
  }, [audioUrl]);

  const onGenerate = () => {
    if (submitting) return;
    setSubmitting(true);
    submitTtsFromJob(renderJobId)
      .then((res) => {
        setSubmitting(false);
        setState({
          phase: 'running',
          ttsJobId: res.tts_job_id,
          progress: 0,
          status: 'queued',
        });
        sseUnsubRef.current?.();
        sseUnsubRef.current = subscribeJobEvents(res.tts_job_id, (ev) => {
          _DISABLED_QWEN3_TTS_handleTtsEvent(ev, setState);
        });
      })
      .catch((err: unknown) => {
        setSubmitting(false);
        setState({
          phase: 'failed',
          ttsJobId: null,
          error: err instanceof Error ? err.message : '提交语音任务失败',
        });
      });
  };

  const onRetry = () => {
    sseUnsubRef.current?.();
    sseUnsubRef.current = null;
    setState({ phase: 'idle' });
  };

  return (
    <div className={`tts-section tts-section--${state.phase}`}>
      <div className="tts-section-head">
        <span className="tts-section-title">TTS 语音合成</span>
        {state.phase === 'running' && (
          <span className={`status-chip status-${state.status}`}>
            {state.status === 'queued' ? '排队中' : '渲染中'}
          </span>
        )}
        {state.phase === 'done' && <span className="status-chip status-done">完成</span>}
        {state.phase === 'failed' && <span className="status-chip status-failed">失败</span>}
      </div>

      {state.phase === 'loading' && (
        <p className="tts-section-empty">正在加载语音任务…</p>
      )}

      {state.phase === 'idle' && (
        <div className="tts-section-row">
          <span className="tts-section-hint">根据本次视频的对话生成 24kHz WAV 语音</span>
          <button
            type="button"
            className="btn btn-primary"
            disabled={submitting}
            onClick={onGenerate}
          >
            {submitting ? '提交中…' : '生成语音'}
          </button>
        </div>
      )}

      {state.phase === 'running' && (
        <div className="tts-section-running">
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{ width: `${Math.max(0, Math.min(100, state.progress))}%` }}
            />
          </div>
          <div className="progress-percent">
            {Math.round(state.progress)}%
          </div>
          <p className="tts-section-empty" style={{ marginTop: 8 }}>
            tts job: <code>{state.ttsJobId}</code>
          </p>
        </div>
      )}

      {state.phase === 'done' && (
        <div className="tts-section-done">
          <div className="tts-section-stats">
            <span className="tts-section-stat">
              <span className="tts-section-stat-label">时长</span>
              <span className="tts-section-stat-value">
                {state.durationSec === null ? '…' : formatDurationSec(state.durationSec)}
              </span>
            </span>
            <span className="tts-section-stat">
              <span className="tts-section-stat-label">失败段</span>
              <span className="tts-section-stat-value">{state.failedCount}</span>
            </span>
          </div>
          {state.audioUrl && (
            <>
              <audio
                controls
                src={state.audioUrl}
                className="tts-section-audio"
              />
              <a
                className="btn btn-sm"
                href={state.audioUrl}
                download={`${state.ttsJobId}.wav`}
              >
                下载 {state.ttsJobId}.wav
              </a>
            </>
          )}
        </div>
      )}

      {state.phase === 'failed' && (
        <div className="tts-section-failed">
          <div className="tts-section-failed-reason">
            reason: {state.error}
          </div>
          <div className="tts-section-row" style={{ marginTop: 8 }}>
            <span />
            <button type="button" className="btn" onClick={onRetry}>
              重新生成
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 把 SSE 事件归并进 TtsPhase。
 * 事件流里没有 job_id —— 通过 prev state 取 ttsJobId。
 * SSE 完成后(浏览器读到流尾 / 后端 done 时)前端不会再收到事件,
 * subscribeJobEvents 内部 done/failed 后自动 return。
 */
function _DISABLED_QWEN3_TTS_handleTtsEvent(
  ev: RenderJobEvent,
  setState: React.Dispatch<React.SetStateAction<_DISABLED_QWEN3_TTS_TtsPhase>>,
): void {
  setState((prev) => {
    if (prev.phase !== 'running') return prev;
    if (ev.status === 'done') {
      const failedCount = ev.metadata_json?.failed_segments?.length ?? 0;
      return {
        phase: 'done',
        ttsJobId: prev.ttsJobId,
        failedCount,
        audioUrl: ev.output_url ?? null,
        durationSec: null,
      };
    }
    if (ev.status === 'failed') {
      return {
        phase: 'failed',
        ttsJobId: prev.ttsJobId,
        error: ev.error ?? '语音合成失败',
      };
    }
    return {
      ...prev,
      status: ev.status,
      progress: typeof ev.progress === 'number' ? ev.progress : prev.progress,
    };
  });
}
