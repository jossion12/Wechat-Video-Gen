import { useEffect, useState } from 'react';
import { previewHtml } from '../api';
import { useDebounce } from '../hooks/useDebounce';
import type { ChatConfig } from '../types';

interface PreviewPanelProps {
  config: ChatConfig;
}

/**
 * 实时预览：防抖 300ms 请求预览 HTML，渲染到 1080×1920 的 iframe 中，
 * 并按 1/3 缩放到 360×640 的手机画框。每次更新更换 iframe key 以重启动画。
 * 配置不完整（少于 2 名参与者或无消息）时不请求后端，显示占位提示。
 */
export function PreviewPanel({ config }: PreviewPanelProps) {
  const debouncedConfig = useDebounce(config, 300);
  const [html, setHtml] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [frameKey, setFrameKey] = useState(0);

  // 后端 ChatConfig 要求至少 2 名参与者、至少 1 条消息,未满足时跳过预览请求
  const ready =
    debouncedConfig.participants.length >= 2 && debouncedConfig.messages.length >= 1;

  useEffect(() => {
    if (!ready) {
      setHtml(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    previewHtml(debouncedConfig)
      .then((h) => {
        if (cancelled) return;
        setHtml(h);
        setFrameKey((k) => k + 1);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : '预览生成失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedConfig, ready]);

  return (
    <section className="card preview-card">
      <div className="preview-head">
        <h2 className="card-title">预览</h2>
        {loading && <span className="preview-loading-tip">预览生成中…</span>}
      </div>
      {error && <div className="preview-error-banner">{error}</div>}
      <div className="phone-frame">
        {html ? (
          <iframe
            key={frameKey}
            className="phone-iframe"
            title="聊天预览"
            srcDoc={html}
            scrolling="no"
          />
        ) : (
          <div className="preview-placeholder">
            {error ? '预览生成失败，请检查后端服务' : '添加参与者和消息后自动生成预览'}
          </div>
        )}
        {loading && html && <div className="preview-overlay">预览生成中…</div>}
      </div>
    </section>
  );
}
