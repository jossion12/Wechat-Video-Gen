import type {
  ContinueDialogueRequest,
  ContinueDialogueResponse,
  FileInfo,
  GenerateDialogueRequest,
  ImportResponse,
  JobStatusResponse,
  Message,
  RenderJobEvent,
  SessionDetail,
  SessionInfo,
  VideoDSL,
} from './types';

/**
 * 鉴权策略(后端 `get_current_user`):
 *   1. `user_id` cookie — 浏览器对 <img>/<iframe>/fetch 同源请求自动带
 *   2. `X-User-Id` header — 仅在显式传入 opts.userId 时使用(给测试 / 反代部署留口子)
 *
 * 这里默认不主动发 X-User-Id,避免跟浏览器 cookie jar 里的 user_id 不一致
 * 触发后端 "cookie / header mismatch" 401。
 */

async function requestJson<T>(
  url: string,
  init?: RequestInit,
  opts: { userId?: string | null } = {},
): Promise<T> {
  const headers = new Headers(init?.headers);
  // 仅在显式 opts.userId 传入时加 X-User-Id;默认走 cookie 鉴权。
  if (opts.userId) {
    headers.set('X-User-Id', opts.userId);
  }

  let res: Response;
  try {
    res = await fetch(url, { ...init, headers });
  } catch {
    throw new Error('网络请求失败，请确认后端服务已启动（http://localhost:8000）');
  }

  if (!res.ok) {
    let detail = `请求失败（HTTP ${res.status}）`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail) {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        // FastAPI 422:取第一条校验错误信息,去掉 pydantic 前缀
        const first = body.detail[0] as { msg?: string } | undefined;
        if (first && typeof first.msg === 'string') {
          detail = first.msg.replace(/^Value error,\s*/i, '');
        }
      } else if (typeof body.detail === 'object' && body.detail !== null) {
        // /api/import 等接口返回的结构化错误: { code, reason, missing, ... }
        const d = body.detail as { code?: string; reason?: string; missing?: string[] };
        detail = d.reason || d.code || detail;
        if (Array.isArray(d.missing) && d.missing.length) {
          detail += `：${d.missing.join(', ')}`;
        }
      }
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(detail);
  }

  return (await res.json()) as T;
}

/** 上传文件（头像、图片素材或背景图），返回服务端存储的 URL。 */
export async function uploadFile(
  file: File,
  kind: 'avatar' | 'image' | 'background',
  sessionId: string,
): Promise<FileInfo> {
  const form = new FormData();
  form.append('file', file);
  form.append('kind', kind);
  form.append('session_id', sessionId);
  return requestJson<FileInfo>('/api/upload', { method: 'POST', body: form });
}

/** 获取预览 HTML 文档字符串。 */
export async function previewHtml(dsl: VideoDSL, sessionId: string): Promise<string> {
  const data = await requestJson<{ html: string }>(
    '/api/preview-html',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dsl, session_id: sessionId }),
    },
  );
  return data.html;
}

/** 提交渲染任务，返回任务 ID。 */
export async function submitRender(dsl: VideoDSL, sessionId: string): Promise<string> {
  const data = await requestJson<{ job_id: string }>(
    '/api/render',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dsl, session_id: sessionId }),
    },
  );
  return data.job_id;
}

/** 查询渲染任务状态。 */
export function getJob(jobId: string): Promise<JobStatusResponse> {
  return requestJson<JobStatusResponse>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

/**
 * 通过 SSE 订阅渲染任务事件（progress / done / failed）。
 * 返回取消订阅函数；done/failed 后流会自动关闭。
 *
 * 注意：浏览器 EventSource 不允许自定义 header，所以我们走 fetch + ReadableStream。
 */
export function subscribeJobEvents(
  jobId: string,
  onEvent: (ev: RenderJobEvent) => void,
): () => void {
  let cancelled = false;
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/events`, {
        // 同源 fetch 默认会带 user_id cookie;不加 X-User-Id,免得跟 cookie 不一致 → 401。
        headers: { Accept: 'text/event-stream' },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        onEvent({ status: 'failed', error: `SSE failed: HTTP ${res.status}` });
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (!cancelled) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          if (frame.startsWith(':')) continue; // 注释/keep-alive
          const dataLine = frame
            .split('\n')
            .find((l) => l.startsWith('data:'));
          if (!dataLine) continue;
          const raw = dataLine.slice(5).trim();
          try {
            const payload = JSON.parse(raw) as RenderJobEvent;
            onEvent(payload);
            if (payload.status === 'done' || payload.status === 'failed') {
              return;
            }
          } catch {
            // ignore
          }
        }
      }
    } catch (err) {
      if (!cancelled) {
        onEvent({
          status: 'failed',
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }
  })();

  return () => {
    cancelled = true;
    controller.abort();
  };
}

// ---------- sessions ----------

export async function createSession(title?: string): Promise<SessionInfo> {
  return requestJson<SessionInfo>('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(title ? { title } : {}),
  });
}

export async function listSessions(): Promise<SessionInfo[]> {
  return requestJson<SessionInfo[]>('/api/sessions');
}

export async function getSessionDetail(sessionId: string): Promise<SessionDetail> {
  return requestJson<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`);
}

export async function deleteSession(sessionId: string): Promise<void> {
  await requestJson<null>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}

/** 导入 zip（DSL + 图片素材）到当前 session。 */
export async function importZip(file: File, sessionId: string): Promise<ImportResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('session_id', sessionId);
  return requestJson<ImportResponse>('/api/import', {
    method: 'POST',
    body: form,
  });
}

// ---------- AI 辅助生成 ----------

export async function getAIQuota(): Promise<{ daily_limit: number; used_today: number; remaining_today: number }> {
  return requestJson('/api/ai/quota');
}

export async function generateDialogue(req: GenerateDialogueRequest): Promise<VideoDSL> {
  return requestJson<VideoDSL>('/api/ai/generate-dialogue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export async function continueDialogue(req: ContinueDialogueRequest): Promise<Message[]> {
  const data = await requestJson<ContinueDialogueResponse>('/api/ai/continue-dialogue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  return data.candidates;
}