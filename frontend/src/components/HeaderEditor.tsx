import type { Mode, WatermarkConfig } from '../types';
import { AvatarPicker } from './common/AvatarPicker';

interface HeaderEditorProps {
  mode: Mode;
  title: string;
  backgroundImage: string | null;
  opacity: number;
  watermark: WatermarkConfig;
  sessionId: string | null;
  onChange: (patch: {
    mode?: Mode;
    title?: string;
    background_image_url?: string | null;
    opacity?: number;
    watermark?: WatermarkConfig;
  }) => void;
}

/** 视频头部设置：聊天模式、标题、背景图片与全局透明度。 */
export function HeaderEditor({
  mode,
  title,
  backgroundImage,
  opacity,
  watermark,
  sessionId,
  onChange,
}: HeaderEditorProps) {
  return (
    <section className="card">
      <h2 className="card-title">视频头部</h2>
      <div className="form-row">
        <span className="form-label">聊天模式</span>
        <div className="radio-group">
          <label className={`radio-option${mode === 'single' ? ' radio-option--active' : ''}`}>
            <input
              type="radio"
              name="chat-mode"
              value="single"
              checked={mode === 'single'}
              onChange={() => onChange({ mode: 'single' })}
            />
            单聊
          </label>
          <label className={`radio-option${mode === 'group' ? ' radio-option--active' : ''}`}>
            <input
              type="radio"
              name="chat-mode"
              value="group"
              checked={mode === 'group'}
              onChange={() => onChange({ mode: 'group' })}
            />
            群聊
          </label>
        </div>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="chat-title">
          聊天标题
        </label>
        <input
          id="chat-title"
          type="text"
          maxLength={30}
          value={title}
          placeholder="例如：家人群 (3)"
          onChange={(e) => onChange({ title: e.target.value })}
        />
      </div>
      <div className="form-row form-row--top">
        <span className="form-label">背景图片</span>
        <div className="background-image-field">
          <AvatarPicker
            kind="background"
            value={backgroundImage}
            onChange={(url) => onChange({ background_image_url: url })}
            alt="聊天背景图"
            sessionId={sessionId}
          />
          <span className="hint">可选，上传后覆盖默认背景，整页平铺显示</span>
        </div>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="chat-opacity">
          全局透明度
        </label>
        <div className="range-field">
          <input
            id="chat-opacity"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={opacity}
            onChange={(e) => onChange({ opacity: parseFloat(e.target.value) })}
          />
          <span className="range-value">{Math.round(opacity * 100)}%</span>
        </div>
      </div>

      <div className="form-row">
        <span className="form-label">飘动水印</span>
        <label className="radio-option">
          <input
            type="checkbox"
            checked={watermark.enabled}
            onChange={(e) =>
              onChange({ watermark: { ...watermark, enabled: e.target.checked } })
            }
          />
          启用(未注册/未充值用户生效)
        </label>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="watermark-text">
          水印内容
        </label>
        <input
          id="watermark-text"
          type="text"
          maxLength={60}
          value={watermark.text}
          placeholder="例如：@AI生成 {date}"
          onChange={(e) =>
            onChange({ watermark: { ...watermark, text: e.target.value } })
          }
        />
        <span className="hint">{'{date} 会自动替换为当天日期'}</span>
      </div>
    </section>
  );
}
