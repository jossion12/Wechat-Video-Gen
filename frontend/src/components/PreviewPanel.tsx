import { useEffect, useState } from 'react';
import { previewHtml } from '../api';
import { useDebounce } from '../hooks/useDebounce';
import type { ChatConfig } from '../types';
import { validateConfig } from '../validate';

interface PreviewPanelProps {
  config: ChatConfig;
}

/**
 * 实时预览：防抖 300ms 请求预览 HTML，渲染到 1080×1920 的 iframe 中，
 * 并按 1/3 缩放到 360×640 的手机画框。每次更新更换 iframe key 以重启动画。
 * 配置不完整（与渲染共用 validateConfig 校验）时不请求后端，显示具体原因。
 */
export function PreviewPanel({ config }: PreviewPanelProps) {
  const debouncedConfig = useDebounce(config, 300);
  const [html, setHtml] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [frameKey, setFrameKey] = useState(0);

  useEffect(() => {
    const problem = validateConfig(debouncedConfig);
    if (problem) {
      // 配置不完整:不发请求,提示具体原因;全空时给更友好的引导文案
      setHtml(null);
      setError(null);
      setLoading(false);
      const empty =
        debouncedConfig.participants.length === 0 && debouncedConfig.messages.length === 0;
      setHint(empty ? '添加参与者和消息后自动生成预览' : problem);
      return;
    }
    let cancelled = false;
    setHint(null);
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
  }, [debouncedConfig]);

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
            {error ? '预览生成失败，请检查后端服务' : hint ?? '添加参与者和消息后自动生成预览'}
          </div>
        )}
        {loading && html && <div className="preview-overlay">预览生成中…</div>}
      </div>
    </section>
  );
}
