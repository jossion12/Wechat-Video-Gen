import { useEffect, useMemo, useState } from 'react';
import { getTimeline } from '../api';
import type { TimelineDocument, TimelineEntry, TimelineEventType } from '../types';

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

/**
 * 时间码查看页:
 *   顶部:任务 id + 总时长 + 下载按钮 + 返回按钮
 *   中部:类型过滤
 *   主体:表格列出每条事件(出现 / 消失 / 持续时长),带简易时间轴预览条
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
        </>
      )}
    </section>
  );
}
