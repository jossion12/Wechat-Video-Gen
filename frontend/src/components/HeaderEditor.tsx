import type { AIBadgeStyle, IntroEffect, Mode, StyleTheme, WatermarkConfig } from '../types';
import { INTRO_EFFECT_LABELS, STYLE_THEME_LABELS } from '../types';
import { AvatarPicker } from './common/AvatarPicker';

import type { ChatScene } from '../types';

interface HeaderEditorProps {
  mode: Mode;
  title: string;
  backgroundImage: string | null;
  opacity: number;
  introEffect: IntroEffect;
  styleTheme: StyleTheme;
  watermark: WatermarkConfig;
  sessionId: string | null;
  onChange: (patch: Partial<ChatScene>) => void;
}

const STYLE_OPTIONS: { value: StyleTheme; label: string }[] = [
  { value: 'cyberpunk', label: STYLE_THEME_LABELS.cyberpunk },
  { value: 'watercolor', label: STYLE_THEME_LABELS.watercolor },
  { value: 'pixel', label: STYLE_THEME_LABELS.pixel },
  { value: 'comic', label: STYLE_THEME_LABELS.comic },
  { value: 'noir', label: STYLE_THEME_LABELS.noir },
  { value: 'ink', label: STYLE_THEME_LABELS.ink },
];

const BADGE_OPTIONS: { value: AIBadgeStyle; label: string }[] = [
  { value: 'neon', label: '霓虹' },
  { value: 'minimal', label: '极简' },
  { value: 'retro', label: '复古印章' },
];

const INTRO_EFFECT_OPTIONS: { value: IntroEffect; label: string }[] = [
  { value: 'none', label: INTRO_EFFECT_LABELS.none },
  { value: 'scanline', label: INTRO_EFFECT_LABELS.scanline },
  { value: 'typewriter', label: INTRO_EFFECT_LABELS.typewriter },
];

/** 视觉风格设置：对话模式、标题、背景图片、透明度与 AI 角标样式。 */
export function HeaderEditor({
  mode,
  title,
  backgroundImage,
  opacity,
  introEffect,
  styleTheme,
  watermark,
  sessionId,
  onChange,
}: HeaderEditorProps) {
  const badgeStyle = watermark.badge_style;
  return (
    <section className="card">
      <h2 className="card-title">视觉风格</h2>
      <div className="form-row">
        <span className="form-label">风格主题</span>
        <div className="radio-group">
          {STYLE_OPTIONS.map((o) => (
            <label
              key={o.value}
              className={`radio-option${styleTheme === o.value ? ' radio-option--active' : ''}`}
            >
              <input
                type="radio"
                name="style-theme"
                value={o.value}
                checked={styleTheme === o.value}
                onChange={() => onChange({ style_theme: o.value })}
              />
              {o.label}
            </label>
          ))}
        </div>
      </div>
      <div className="form-row">
        <span className="form-label">对话模式</span>
        <div className="radio-group">
          <label className={`radio-option${mode === 'single' ? ' radio-option--active' : ''}`}>
            <input
              type="radio"
              name="chat-mode"
              value="single"
              checked={mode === 'single'}
              onChange={() => onChange({ mode: 'single' })}
            />
            对谈
          </label>
          <label className={`radio-option${mode === 'group' ? ' radio-option--active' : ''}`}>
            <input
              type="radio"
              name="chat-mode"
              value="group"
              checked={mode === 'group'}
              onChange={() => onChange({ mode: 'group' })}
            />
            群像
          </label>
        </div>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="chat-title">
          标题
        </label>
        <input
          id="chat-title"
          type="text"
          maxLength={30}
          value={title}
          placeholder="例如：雨夜便利店"
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
            alt="背景图"
            sessionId={sessionId}
          />
          <span className="hint">可选，上传后以低透明度叠加在深色背景上</span>
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
        <span className="form-label">开头特效</span>
        <div className="radio-group">
          {INTRO_EFFECT_OPTIONS.map((o) => (
            <label
              key={o.value}
              className={`radio-option${introEffect === o.value ? ' radio-option--active' : ''}`}
            >
              <input
                type="radio"
                name="intro-effect"
                value={o.value}
                checked={introEffect === o.value}
                onChange={() => onChange({ intro_effect: o.value })}
              />
              {o.label}
            </label>
          ))}
        </div>
      </div>

      <div className="form-row">
        <span className="form-label">AI 角标</span>
        <div className="radio-group">
          {BADGE_OPTIONS.map((o) => (
            <label
              key={o.value}
              className={`radio-option${badgeStyle === o.value ? ' radio-option--active' : ''}`}
            >
              <input
                type="radio"
                name="badge-style"
                value={o.value}
                checked={badgeStyle === o.value}
                onChange={() =>
                  onChange({ watermark: { ...watermark, badge_style: o.value } })
                }
              />
              {o.label}
            </label>
          ))}
        </div>
      </div>
      <p className="hint">AI 生成标识不可关闭，仅可切换视觉样式。</p>
    </section>
  );
}
