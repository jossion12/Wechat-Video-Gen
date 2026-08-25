import type { ChatScene, Participant, TransparentFormat } from '../types';
import {
  INTENT_LABELS,
  INTRO_EFFECT_LABELS,
  STYLE_THEME_LABELS,
  TRANSPARENT_FORMAT_LABELS,
} from '../types';

interface SummaryStepProps {
  scene: ChatScene;
  // 透明背景输出选项 —— 详见 docs/09-how-to-make-package.md §4.3。
  transparent: boolean;
  transparent_format: TransparentFormat | null;
  onOutputChange: (patch: {
    transparent?: boolean;
    transparent_format?: TransparentFormat | null;
  }) => void;
}

const TRANSPARENT_FORMATS: TransparentFormat[] = ['webm_vp9_alpha', 'mov_prores4444'];

export function SummaryStep({
  scene,
  transparent,
  transparent_format,
  onOutputChange,
}: SummaryStepProps) {
  const names = scene.participants
    .slice(0, 4)
    .map((p: Participant) => p.name || p.id)
    .join('、');
  const more = scene.participants.length > 4 ? ` 等 ${scene.participants.length} 人` : '';
  // 没显式选过格式但勾选了透明,UI 默认给 webm_vp9_alpha,
  // 与后端 _resolve_output_ext 的默认行为保持一致。
  const effectiveFormat: TransparentFormat =
    transparent_format ?? 'webm_vp9_alpha';

  return (
    <section className="card">
      <h2 className="card-title">全场景总览</h2>
      <div className="summary-grid">
        <div className="summary-item">
          <span className="summary-label">创作意图</span>
          <span className="summary-value">{INTENT_LABELS[scene.intent] ?? scene.intent}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">风格主题</span>
          <span className="summary-value">{STYLE_THEME_LABELS[scene.style_theme] ?? scene.style_theme}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">对话模式</span>
          <span className="summary-value">
            {scene.mode === 'single' ? '对谈' : '群像'}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">标题</span>
          <span className="summary-value">{scene.title}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">背景</span>
          <span className="summary-value">
            {scene.background_image_url ? '图片背景' : scene.background}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">角色</span>
          <span className="summary-value">
            {scene.participants.length > 0 ? `${names}${more}` : '未添加'}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">消息数</span>
          <span className="summary-value">{scene.messages.length} 条</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">开头特效</span>
          <span className="summary-value">
            {INTRO_EFFECT_LABELS[scene.intro_effect] ?? scene.intro_effect}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">AI 角标</span>
          <span className="summary-value">{scene.watermark.badge_style}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">输出格式</span>
          <span className="summary-value">
            {transparent
              ? TRANSPARENT_FORMAT_LABELS[effectiveFormat]
              : 'MP4 (H.264, 不透明)'}
          </span>
        </div>
      </div>

      <div className="output-options">
        <h3 className="output-options-title">输出选项</h3>
        <div className="form-row form-row--top">
          <span className="form-label">背景</span>
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={transparent}
              onChange={(e) => onOutputChange({ transparent: e.target.checked })}
            />
            <span>透明背景输出</span>
          </label>
        </div>
        {transparent && (
          <div className="form-row form-row--top">
            <span className="form-label">封装格式</span>
            <select
              value={effectiveFormat}
              onChange={(e) =>
                onOutputChange({ transparent_format: e.target.value as TransparentFormat })
              }
            >
              {TRANSPARENT_FORMATS.map((fmt) => (
                <option key={fmt} value={fmt}>
                  {TRANSPARENT_FORMAT_LABELS[fmt]}
                </option>
              ))}
            </select>
            <p className="hint hint--inline">
              WebM 体量小、浏览器友好；MOV (ProRes 4444) 适合专业剪辑，但浏览器需下载后用
              QuickTime / VLC 播放。
            </p>
          </div>
        )}
      </div>
    </section>
  );
}