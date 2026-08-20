import type { CSSProperties, ReactNode } from 'react';
import type { ChatScene, Message, Participant, StyleTheme } from '../types';

interface StaticPreviewProps {
  step: 1 | 2 | 3 | 4;
  scene: ChatScene;
}

function stringToColor(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const c = (hash & 0x00ffffff).toString(16).padStart(6, '0');
  return `#${c}`;
}

function getInitial(name: string, id: string): string {
  return (name || id).slice(0, 1).toUpperCase();
}

function defaultIsRight(senderId: string, participants: Participant[], mode: ChatScene['mode']): boolean {
  if (participants.length === 0) return false;
  if (mode === 'single') return senderId === participants[0].id;
  return senderId === 'me';
}

function isRightSide(message: Message, participants: Participant[], mode: ChatScene['mode']): boolean {
  if (message.align === 'right') return true;
  if (message.align === 'left') return false;
  return defaultIsRight(message.sender_id, participants, mode);
}

function findParticipant(id: string, participants: Participant[]): Participant | undefined {
  return participants.find((p) => p.id === id);
}

function themeClass(base: string, theme: StyleTheme): string {
  return `${base} ${base}--${theme}`;
}

function Avatar({
  participant,
  fallbackId,
  theme,
}: {
  participant?: Participant;
  fallbackId: string;
  theme: StyleTheme;
}) {
  const id = participant?.id || fallbackId;
  const name = participant?.name || '';
  const url = participant?.avatar_url;
  return (
    <div className={themeClass('sp-avatar', theme)} style={{ backgroundColor: stringToColor(id) }}>
      {url ? <img src={url} alt={name || id} /> : <span>{getInitial(name, id)}</span>}
    </div>
  );
}

function ChatHeader({ scene, theme }: { scene: ChatScene; theme: StyleTheme }) {
  return (
    <div className={themeClass('sp-header', theme)}>
      <div className="sp-header-title">{scene.title}</div>
    </div>
  );
}

function ChatContent({ scene, theme, children }: { scene: ChatScene; theme: StyleTheme; children: ReactNode }) {
  const style: CSSProperties = {
    backgroundColor: scene.background,
    backgroundImage: scene.background_image_url ? `url(${scene.background_image_url})` : undefined,
    backgroundSize: 'cover',
    backgroundPosition: 'center',
  };
  return (
    <div className={themeClass('sp-content', theme)} style={style}>
      {children}
    </div>
  );
}

function MessageSkeletons({ theme }: { theme: StyleTheme }) {
  return (
    <div className="sp-skeleton-list">
      <div className="sp-skeleton-row sp-skeleton-row--left">
        <div className={`sp-skeleton-bubble sp-skeleton-bubble--${theme}`} style={{ width: 140 }} />
      </div>
      <div className="sp-skeleton-row sp-skeleton-row--right">
        <div className={`sp-skeleton-bubble sp-skeleton-bubble--${theme}`} style={{ width: 120 }} />
      </div>
      <div className="sp-skeleton-row sp-skeleton-row--left">
        <div className={`sp-skeleton-bubble sp-skeleton-bubble--${theme}`} style={{ width: 180 }} />
      </div>
    </div>
  );
}

function ParticipantSkeletons({ theme }: { theme: StyleTheme }) {
  return (
    <div className="sp-participant-row">
      {[1, 2, 3].map((i) => (
        <div key={i} className="sp-participant-chip">
          <div className={themeClass('sp-avatar', theme)} style={{ background: '#33334d' }}>
            <span>{String.fromCharCode(64 + i)}</span>
          </div>
          <span className="sp-participant-name">角色 {i}</span>
        </div>
      ))}
    </div>
  );
}

function ParticipantAvatarRow({ participants, theme }: { participants: Participant[]; theme: StyleTheme }) {
  if (participants.length === 0) {
    return <ParticipantSkeletons theme={theme} />;
  }
  return (
    <div className="sp-participant-row">
      {participants.map((p) => (
        <div key={p.id} className="sp-participant-chip">
          <Avatar participant={p} fallbackId={p.id} theme={theme} />
          <span className="sp-participant-name">{p.name || p.id}</span>
        </div>
      ))}
    </div>
  );
}

function MessageListPreview({
  messages,
  participants,
  mode,
  theme,
}: {
  messages: Message[];
  participants: Participant[];
  mode: ChatScene['mode'];
  theme: StyleTheme;
}) {
  const visible = messages.slice(0, 8);
  if (visible.length === 0) {
    return <MessageSkeletons theme={theme} />;
  }
  return (
    <div className="sp-message-list">
      {visible.map((m, i) => {
        if (m.kind === 'sys' || m.kind === 'timestamp') {
          return (
            <div key={i} className={`sp-message sp-message--system sp-message--system-${theme}`}>
              <span>{m.text || (m.kind === 'sys' ? '幕间字幕' : '时间戳')}</span>
            </div>
          );
        }
        const sender = findParticipant(m.sender_id, participants);
        const right = isRightSide(m, participants, mode);
        return (
          <div key={i} className={`sp-message${right ? ' sp-message--me' : ''}`}>
            <Avatar participant={sender} fallbackId={m.sender_id} theme={theme} />
            <div className={`sp-bubble sp-bubble--${theme}${right ? ' sp-bubble--me' : ' sp-bubble--other'}`}>
              {m.kind === 'text' && <span>{m.text || ' '}</span>}
              {m.kind === 'image' && <span className="sp-bubble-media">图片</span>}
              {m.kind === 'video' && <span className="sp-bubble-media">▶ 视频</span>}
              {m.kind === 'emoji' && <span>{m.text || 'emoji'}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StepPreview({ scene, theme, showParticipants = false, showMessages = false }: {
  scene: ChatScene;
  theme: StyleTheme;
  showParticipants?: boolean;
  showMessages?: boolean;
}) {
  return (
    <>
      <ChatHeader scene={scene} theme={theme} />
      <ChatContent scene={scene} theme={theme}>
        {showParticipants && <ParticipantAvatarRow participants={scene.participants} theme={theme} />}
        {showMessages ? (
          <MessageListPreview messages={scene.messages} participants={scene.participants} mode={scene.mode} theme={theme} />
        ) : (
          <MessageSkeletons theme={theme} />
        )}
      </ChatContent>
    </>
  );
}

/**
 * 纯前端静态预览：步骤 1~4 直接 React 渲染对话剧场局部界面，
 * 不调用后端 previewHtml，也不使用 iframe。
 */
export function StaticPreview({ step, scene }: StaticPreviewProps) {
  const theme = scene.style_theme;
  const style: CSSProperties = { opacity: scene.opacity };
  return (
    <section className="card preview-card">
      <div className="preview-head">
        <h2 className="card-title">预览</h2>
      </div>
      <div className="phone-frame">
        <div className={`static-preview static-preview--${theme}`} style={style}>
          {step === 1 && <StepPreview scene={scene} theme={theme} />}
          {step === 2 && <StepPreview scene={scene} theme={theme} />}
          {step === 3 && <StepPreview scene={scene} theme={theme} showParticipants />}
          {step === 4 && <StepPreview scene={scene} theme={theme} showMessages />}
        </div>
      </div>
    </section>
  );
}
