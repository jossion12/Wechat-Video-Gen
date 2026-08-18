import type { Mode } from '../types';

interface HeaderEditorProps {
  mode: Mode;
  title: string;
  background: string;
  onChange: (patch: { mode?: Mode; title?: string; background?: string }) => void;
}

/** 视频头部设置：聊天模式、标题、背景颜色。 */
export function HeaderEditor({ mode, title, background, onChange }: HeaderEditorProps) {
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
          placeholder="例如：后宫风云复盘群 (3)"
          onChange={(e) => onChange({ title: e.target.value })}
        />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="chat-background">
          背景颜色
        </label>
        <div className="color-field">
          <input
            id="chat-background"
            type="color"
            value={background}
            onChange={(e) => onChange({ background: e.target.value })}
          />
          <span className="color-value">{background}</span>
        </div>
      </div>
    </section>
  );
}
