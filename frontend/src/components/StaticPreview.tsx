import type { CSSProperties, ReactNode } from 'react';
import type { ChatScene, Message, Participant } from '../types';

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

function Avatar({
  participant,
  fallbackId,
  small = false,
}: {
  participant?: Participant;
  fallbackId: string;
  small?: boolean;
}) {
  const id = participant?.id || fallbackId;
  const name = participant?.name || '';
  const url = participant?.avatar_url;
  return (
    <div
      className={`sp-avatar${small ? ' sp-avatar--small' : ''}`}
      style={{ backgroundColor: stringToColor(id) }}
    >
      {url ? <img src={url} alt={name || id} /> : <span>{getInitial(name, id)}</span>}
    </div>
  );
}

/** 根据电池百分比 0-100 挑出对应 fluentui Battery 图标 (1~10 档)。 */
function batteryIconSrc(level: number): string {
  const idx = Math.max(0, Math.min(10, Math.round(level / 10)));
  return `/icons/status-bar/battery-${idx}.svg`;
}

function StatusBarPreview({
  statusBar,
  emphasized = false,
}: {
  statusBar: ChatScene['status_bar'];
  emphasized?: boolean;
}) {
  return (
    <div className={`sp-status-bar${emphasized ? ' sp-status-bar--emphasized' : ''}`}>
      <div className="sp-status-left">
        <span className="sp-status-time">{statusBar.time}</span>
      </div>
      <div className="sp-status-right">
        {statusBar.show_alarm && (
          <img className="sp-icon sp-icon-24" src="/icons/status-bar/alarm-24.svg" alt="alarm" />
        )}
        {statusBar.show_bluetooth && (
          <img className="sp-icon sp-icon-bt" src="/icons/status-bar/bluetooth-24.svg" alt="bluetooth" />
        )}
        {statusBar.show_wifi && (
          <img className="sp-icon sp-icon-wifi" src="/icons/status-bar/wifi-24.svg" alt="wifi" />
        )}
        {statusBar.show_signal && (
          <div className="sp-signal">
            {statusBar.signal_type && (
              <span className="sp-signal-type">{statusBar.signal_type}</span>
            )}
            <div className="sp-signal-bars">
              <span style={{ height: 6 }} />
              <span style={{ height: 8 }} />
              <span style={{ height: 10 }} />
              <span style={{ height: 12 }} />
            </div>
          </div>
        )}
        {statusBar.dual_sim && statusBar.signal_type_secondary && (
          <div className="sp-signal sp-signal--sub">
            <span className="sp-signal-type">{statusBar.signal_type_secondary}</span>
            <div className="sp-signal-bars">
              <span style={{ height: 6 }} />
              <span style={{ height: 8 }} />
              <span style={{ height: 10 }} />
              <span style={{ height: 12 }} />
            </div>
          </div>
        )}
        <div className="sp-battery">
          <span className="sp-battery-wrap">
            <img
              className="sp-icon sp-icon-battery"
              src={batteryIconSrc(statusBar.battery_level)}
              alt="battery"
            />
          </span>
        </div>
      </div>
    </div>
  );
}

function ChatHeader({ scene, showSubtitle = false }: { scene: ChatScene; showSubtitle?: boolean }) {
  const countText = scene.mode === 'group' && scene.participants.length > 0
    ? `(${scene.participants.length})`
    : '';
  return (
    <div className="sp-header">
      <div className="sp-header-left">
        <span className="sp-header-mode">{scene.mode === 'single' ? '单聊' : '群聊'}</span>
        {countText && <span className="sp-header-count">{countText}</span>}
      </div>
      <div className="sp-header-center">
        <div className="sp-header-title">{scene.title}</div>
        {showSubtitle && scene.subtitle && (
          <div className="sp-header-subtitle">{scene.subtitle}</div>
        )}
      </div>
      <div className="sp-header-right">
        <span className="sp-header-dot" />
        <span className="sp-header-dot" />
        <span className="sp-header-dot" />
      </div>
    </div>
  );
}

function ChatContent({ scene, children }: { scene: ChatScene; children: ReactNode }) {
  const style: CSSProperties = {
    backgroundColor: scene.background,
    backgroundImage: scene.background_image_url ? `url(${scene.background_image_url})` : undefined,
    backgroundSize: 'cover',
    backgroundPosition: 'center',
  };
  return (
    <div className="sp-content" style={style}>
      {children}
    </div>
  );
}

function MessageSkeletons() {
  return (
    <div className="sp-skeleton-list">
      <div className="sp-skeleton-row sp-skeleton-row--left">
        <div className="sp-skeleton-bubble" style={{ width: 140 }} />
      </div>
      <div className="sp-skeleton-row sp-skeleton-row--right">
        <div className="sp-skeleton-bubble" style={{ width: 120 }} />
      </div>
      <div className="sp-skeleton-row sp-skeleton-row--left">
        <div className="sp-skeleton-bubble" style={{ width: 180 }} />
      </div>
      <div className="sp-skeleton-row sp-skeleton-row--left">
        <div className="sp-skeleton-bubble" style={{ width: 100 }} />
      </div>
      <div className="sp-skeleton-row sp-skeleton-row--right">
        <div className="sp-skeleton-bubble" style={{ width: 150 }} />
      </div>
    </div>
  );
}

function ParticipantSkeletons() {
  return (
    <div className="sp-participant-row">
      {[1, 2, 3].map((i) => (
        <div key={i} className="sp-participant-chip">
          <div className="sp-avatar" style={{ background: '#d1d5db' }}>
            <span>{String.fromCharCode(64 + i)}</span>
          </div>
          <span className="sp-participant-name">参与者 {i}</span>
        </div>
      ))}
    </div>
  );
}

function ParticipantAvatarRow({ participants }: { participants: Participant[] }) {
  if (participants.length === 0) {
    return <ParticipantSkeletons />;
  }
  return (
    <div className="sp-participant-row">
      {participants.map((p) => (
        <div key={p.id} className="sp-participant-chip">
          <Avatar participant={p} fallbackId={p.id} />
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
}: {
  messages: Message[];
  participants: Participant[];
  mode: ChatScene['mode'];
}) {
  const visible = messages.slice(0, 8);
  if (visible.length === 0) {
    return <MessageSkeletons />;
  }
  return (
    <div className="sp-message-list">
      {visible.map((m, i) => {
        if (m.kind === 'sys' || m.kind === 'timestamp') {
          return (
            <div key={i} className="sp-message sp-message--system">
              <span>{m.text || (m.kind === 'sys' ? '系统消息' : '时间戳')}</span>
            </div>
          );
        }
        const sender = findParticipant(m.sender_id, participants);
        const right = isRightSide(m, participants, mode);
        return (
          <div key={i} className={`sp-message${right ? ' sp-message--me' : ''}`}>
            <Avatar participant={sender} fallbackId={m.sender_id} small />
            <div className="sp-bubble">
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

function Step1Preview({ scene }: { scene: ChatScene }) {
  return (
    <>
      <StatusBarPreview statusBar={scene.status_bar} />
      <ChatHeader scene={scene} />
      <ChatContent scene={scene}>
        <MessageSkeletons />
      </ChatContent>
    </>
  );
}

function Step2Preview({ scene }: { scene: ChatScene }) {
  return (
    <>
      <StatusBarPreview statusBar={scene.status_bar} emphasized />
      <ChatHeader scene={scene} />
      <ChatContent scene={scene}>
        <MessageSkeletons />
      </ChatContent>
    </>
  );
}

function Step3Preview({ scene }: { scene: ChatScene }) {
  return (
    <>
      <StatusBarPreview statusBar={scene.status_bar} />
      <ChatHeader scene={scene} showSubtitle={scene.mode === 'single'} />
      <ChatContent scene={scene}>
        <ParticipantAvatarRow participants={scene.participants} />
        <MessageSkeletons />
      </ChatContent>
    </>
  );
}

function Step4Preview({ scene }: { scene: ChatScene }) {
  return (
    <>
      <StatusBarPreview statusBar={scene.status_bar} />
      <ChatHeader scene={scene} />
      <ChatContent scene={scene}>
        <MessageListPreview messages={scene.messages} participants={scene.participants} mode={scene.mode} />
      </ChatContent>
    </>
  );
}

/**
 * 纯前端静态预览：步骤 1~4 直接 React 渲染微信聊天局部界面，
 * 不调用后端 previewHtml，也不使用 iframe。
 */
export function StaticPreview({ step, scene }: StaticPreviewProps) {
  const style: CSSProperties = { opacity: scene.opacity };
  return (
    <section className="card preview-card">
      <div className="preview-head">
        <h2 className="card-title">预览</h2>
      </div>
      <div className="phone-frame">
        <div className="static-preview" style={style}>
          {step === 1 && <Step1Preview scene={scene} />}
          {step === 2 && <Step2Preview scene={scene} />}
          {step === 3 && <Step3Preview scene={scene} />}
          {step === 4 && <Step4Preview scene={scene} />}
        </div>
      </div>
    </section>
  );
}
