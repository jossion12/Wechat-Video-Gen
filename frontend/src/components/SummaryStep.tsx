import type { ChatScene, Participant } from '../types';
import { INTENT_LABELS, INTRO_EFFECT_LABELS, STYLE_THEME_LABELS } from '../types';

interface SummaryStepProps {
  scene: ChatScene;
}

export function SummaryStep({ scene }: SummaryStepProps) {
  const names = scene.participants
    .slice(0, 4)
    .map((p: Participant) => p.name || p.id)
    .join('、');
  const more = scene.participants.length > 4 ? ` 等 ${scene.participants.length} 人` : '';

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
      </div>
    </section>
  );
}
