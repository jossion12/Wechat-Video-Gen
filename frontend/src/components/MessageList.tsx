import type { Message, MessageKind, Participant } from '../types';
import { AvatarPicker } from './common/AvatarPicker';

const SYSTEM_ID = '__system__';
const MAX_MESSAGES = 30;

const KIND_OPTIONS: { value: MessageKind; label: string }[] = [
  { value: 'text', label: '文字' },
  { value: 'image', label: '图片' },
  { value: 'sys', label: '系统消息' },
];

interface MessageListProps {
  participants: Participant[];
  messages: Message[];
  onChange: (messages: Message[]) => void;
}

/** 消息列表：类型、发送者、内容、图片、间隔时间与排序操作。 */
export function MessageList({ participants, messages, onChange }: MessageListProps) {
  const updateAt = (index: number, patch: Partial<Message>) => {
    onChange(messages.map((m, i) => (i === index ? { ...m, ...patch } : m)));
  };

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= messages.length) return;
    const next = [...messages];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const removeAt = (index: number) => {
    onChange(messages.filter((_, i) => i !== index));
  };

  const addMessage = () => {
    if (messages.length >= MAX_MESSAGES) return;
    const sender = participants[0]?.id ?? SYSTEM_ID;
    onChange([
      ...messages,
      { sender_id: sender, kind: 'text', text: '', image_url: null, delay_ms: 1500 },
    ]);
  };

  return (
    <section className="card">
      <h2 className="card-title">
        消息（{messages.length}/{MAX_MESSAGES}）
      </h2>
      <ul className="message-list">
        {messages.map((m, i) => {
          const isSys = m.kind === 'sys';
          return (
            <li key={i} className="message-row">
              <div className="message-row-top">
                <select
                  className="kind-select"
                  value={m.kind}
                  onChange={(e) => {
                    const kind = e.target.value as MessageKind;
                    updateAt(i, {
                      kind,
                      sender_id: kind === 'sys' ? SYSTEM_ID : m.sender_id,
                    });
                  }}
                >
                  {KIND_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <select
                  className="sender-select"
                  value={m.sender_id}
                  disabled={isSys}
                  onChange={(e) => updateAt(i, { sender_id: e.target.value })}
                >
                  {isSys ? (
                    <option value={SYSTEM_ID}>系统</option>
                  ) : (
                    participants.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name || p.id}
                      </option>
                    ))
                  )}
                </select>
              </div>
              <textarea
                className="message-text"
                rows={2}
                maxLength={500}
                placeholder={
                  isSys ? '系统消息内容' : m.kind === 'image' ? '图片说明（可选）' : '消息内容'
                }
                value={m.text ?? ''}
                onChange={(e) => updateAt(i, { text: e.target.value })}
              />
              {m.kind === 'image' && (
                <div className="message-image-row">
                  <AvatarPicker
                    kind="image"
                    value={m.image_url}
                    onChange={(url) => updateAt(i, { image_url: url })}
                    alt="消息图片"
                  />
                  {!m.image_url && <span className="hint">请上传图片素材（视频中的聊天图片）</span>}
                </div>
              )}
              <div className="message-meta">
                <label className="delay-field">
                  间隔
                  <input
                    type="number"
                    min={0}
                    step={100}
                    value={m.delay_ms}
                    onChange={(e) => {
                      const v = Number.parseInt(e.target.value, 10);
                      updateAt(i, { delay_ms: Number.isNaN(v) ? 1500 : Math.max(0, v) });
                    }}
                  />
                  ms
                </label>
                <div className="message-actions">
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                  >
                    上移
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={i === messages.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    下移
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    onClick={() => removeAt(i)}
                  >
                    删除
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={messages.length >= MAX_MESSAGES}
        onClick={addMessage}
      >
        添加消息
      </button>
    </section>
  );
}
