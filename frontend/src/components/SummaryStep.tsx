import type { ChatScene, Participant } from '../types';

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
          <span className="summary-label">聊天模式</span>
          <span className="summary-value">
            {scene.mode === 'single' ? '单聊' : '群聊'}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">聊天标题</span>
          <span className="summary-value">{scene.title}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">背景</span>
          <span className="summary-value">
            {scene.background_image_url ? '图片背景' : scene.background}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">参与人</span>
          <span className="summary-value">
            {scene.participants.length > 0 ? `${names}${more}` : '未添加'}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">消息数</span>
          <span className="summary-value">{scene.messages.length} 条</span>
        </div>
      </div>
    </section>
  );
}
