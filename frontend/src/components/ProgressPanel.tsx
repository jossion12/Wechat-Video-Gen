import { useRenderJob } from '../hooks/useRenderJob';
import type { JobStatus, OutputExt } from '../types';
import { OUTPUT_EXT_LABELS } from '../types';

interface ProgressPanelProps {
  jobId: string | null;
  /** 触发时间码视图(由 App 注入) — 仅 status==='done' 且 timeline_url 非空时按钮可见 */
  onViewTimeline?: () => void;
}

const STATUS_TEXT: Record<JobStatus, string> = {
  queued: '排队中',
  running: '录制中',
  done: '已完成',
  failed: '失败',
};

/** 渲染进度面板：状态、进度条、下载与错误提示。 */
export function ProgressPanel({ jobId, onViewTimeline }: ProgressPanelProps) {
  const { job, error, loading } = useRenderJob(jobId);

  if (!jobId) {
    return (
      <section className="card progress-card">
        <h2 className="card-title">渲染进度</h2>
        <p className="progress-empty">尚未提交渲染任务。编辑左侧内容后点击「生成视频」。</p>
      </section>
    );
  }

  if (loading && !job) {
    return (
      <section className="card progress-card">
        <h2 className="card-title">渲染进度</h2>
        <p className="progress-empty">正在获取任务状态…</p>
      </section>
    );
  }

  if (error && !job) {
    return (
      <section className="card progress-card">
        <h2 className="card-title">渲染进度</h2>
        <div className="error-text">{error}</div>
      </section>
    );
  }

  if (!job) return null;

  const pct = Math.max(0, Math.min(100, job.progress));
  // 老 job 可能没有 output_ext 字段,默认按 mp4 处理以保证 UI 不崩。
  const outputExt: OutputExt = job.output_ext ?? 'mp4';
  const downloadName = `video.${outputExt}`;
  const downloadLabel = `下载 ${OUTPUT_EXT_LABELS[outputExt]}`;

  return (
    <section className="card progress-card">
      <h2 className="card-title">渲染进度</h2>
      <div className="progress-header">
        <span className={`status-chip status-${job.status}`}>{STATUS_TEXT[job.status]}</span>
        <span className="progress-percent">{Math.round(pct)}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {job.status === 'failed' && (
        <div className="error-text">{job.error ?? '渲染失败，未知错误'}</div>
      )}
      {job.status === 'done' && job.output_url && (
        <a
          className="btn btn-primary download-btn"
          href={job.output_url}
          download={downloadName}
        >
          {downloadLabel}
        </a>
      )}
      {job.status === 'done' && job.timeline_url && onViewTimeline && (
        <button
          type="button"
          className="btn btn-ghost download-btn"
          onClick={onViewTimeline}
        >
          查看时间码
        </button>
      )}
    </section>
  );
}