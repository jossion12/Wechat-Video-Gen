import type { ChatConfig, JobStatusResponse, RenderJobEvent } from './types';

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error('网络请求失败，请确认后端服务已启动（http://localhost:8000）');
  }

  if (!res.ok) {
    let detail = `请求失败（HTTP ${res.status}）`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (typeof body.detail === 'string' && body.detail) {
        detail = body.detail;
      }
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(detail);
  }

  return (await res.json()) as T;
}

/** 上传文件（头像或图片素材），返回服务端存储的 URL。 */
export async function uploadFile(
  file: File,
  kind: 'avatar' | 'image',
): Promise<{ url: string; kind: string }> {
  const form = new FormData();
  form.append('file', file);
  form.append('kind', kind);
  return requestJson<{ url: string; kind: string }>('/api/upload', {
    method: 'POST',
    body: form,
  });
}

/** 获取预览 HTML 文档字符串。 */
export async function previewHtml(config: ChatConfig): Promise<string> {
  const data = await requestJson<{ html: string }>('/api/preview-html', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return data.html;
}

/** 提交渲染任务，返回任务 ID。 */
export async function submitRender(config: ChatConfig): Promise<string> {
  const data = await requestJson<{ job_id: string }>('/api/render', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return data.job_id;
}

/** 查询渲染任务状态。 */
export function getJob(jobId: string): Promise<JobStatusResponse> {
  return requestJson<JobStatusResponse>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

/**
 * 通过 SSE 订阅渲染任务事件（progress / done / failed）。
 * 返回取消订阅函数；done/failed 后流会自动关闭。
 */
export function subscribeJobEvents(
  jobId: string,
  onEvent: (ev: RenderJobEvent) => void,
): () => void {
  const source = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);

  const handle = (raw: MessageEvent<string>) => {
    let payload: RenderJobEvent;
    try {
      payload = JSON.parse(raw.data) as RenderJobEvent;
    } catch {
      return; // 忽略无法解析的事件
    }
    onEvent(payload);
    if (payload.status === 'done' || payload.status === 'failed') {
      source.close();
    }
  };

  source.addEventListener('progress', handle);
  source.addEventListener('done', handle);
  source.addEventListener('failed', handle);
  source.onerror = () => {
    // 流被服务端关闭（或网络异常）时也关闭连接，避免无限重连
    source.close();
  };

  return () => {
    source.close();
  };
}
