import { useRenderJob } from '../hooks/useRenderJob';
import type { JobStatus } from '../types';

interface ProgressPanelProps {
  jobId: string | null;
}

const STATUS_TEXT: Record<JobStatus, string> = {
  queued: '排队中',
  running: '录制中',
  done: '已完成',
  failed: '失败',
};

/** 渲染进度面板：状态、进度条、下载与错误提示。 */
export function ProgressPanel({ jobId }: ProgressPanelProps) {
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
        <a className="btn btn-primary download-btn" href={job.output_url} download>
          下载 MP4
        </a>
      )}
    </section>
  );
}
