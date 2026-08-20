import type { Intent } from '../types';
import { INTENT_LABELS } from '../types';

interface IntentStepProps {
  intent: Intent | '';
  acknowledged: boolean;
  onChange: (patch: { intent?: Intent; intent_acknowledged?: boolean }) => void;
}

const INTENTS: Intent[] = [
  'short_video_drama',
  'story_visualization',
  'teaching_simulation',
  'meme_sticker',
];

export function IntentStep({ intent, acknowledged, onChange }: IntentStepProps) {
  return (
    <section className="card">
      <h2 className="card-title">创作意图</h2>
      <p className="hint">选择你将如何使用本作品，这有助于我们确保内容合规。</p>

      <div className="form-row form-row--top">
        <span className="form-label">使用场景</span>
        <div className="radio-group radio-group--vertical">
          {INTENTS.map((key) => (
            <label
              key={key}
              className={`radio-option radio-option--block${intent === key ? ' radio-option--active' : ''}`}
            >
              <input
                type="radio"
                name="intent"
                value={key}
                checked={intent === key}
                onChange={() => onChange({ intent: key })}
              />
              {INTENT_LABELS[key]}
            </label>
          ))}
        </div>
      </div>

      <div className="form-row form-row--top">
        <span className="form-label">合规承诺</span>
        <label className="checkbox-option checkbox-option--agreement">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => onChange({ intent_acknowledged: e.target.checked })}
          />
          <span>
            我承诺：本作品仅用于创意表达、教学演示或合法创作场景，不会用于伪造证据、金融诈骗、冒充他人或诽谤。
          </span>
        </label>
      </div>

      <div className="prohibited-list">
        <p className="prohibited-title">明确禁止：</p>
        <ul>
          <li>伪造证据、聊天记录或转账截图</li>
          <li>金融诈骗、冒充他人身份</li>
          <li>诽谤、骚扰或侵犯他人肖像权</li>
          <li>模仿微信、WhatsApp 等真实平台界面</li>
        </ul>
      </div>
    </section>
  );
}
