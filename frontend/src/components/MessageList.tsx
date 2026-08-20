import { useRef, useState } from 'react';
import type { Message, MessageKind, Participant } from '../types';
import { AvatarPicker } from './common/AvatarPicker';

const SYSTEM_ID = '__system__';
const MAX_MESSAGES = 30;

const KIND_OPTIONS: { value: MessageKind; label: string }[] = [
  { value: 'text', label: '文字' },
  { value: 'image', label: '图片' },
  { value: 'sys', label: '系统消息' },
];

const ALIGN_OPTIONS: { value: 'auto' | 'left' | 'right'; label: string }[] = [
  { value: 'auto', label: '自动' },
  { value: 'left', label: '左' },
  { value: 'right', label: '右' },
];

const DEFAULT_EMOJIS = [
  '😀',
  '😂',
  '🤣',
  '❤️',
  '👍',
  '🙏',
  '😭',
  '😘',
  '🥰',
  '😊',
  '🤔',
  '😎',
  '😡',
  '🎉',
  '🔥',
  '💯',
  '🌹',
  '👏',
  '🤗',
  '🥳',
];

interface MessageListProps {
  participants: Participant[];
  messages: Message[];
  sessionId: string | null;
  onChange: (messages: Message[]) => void;
}

/** 消息列表：类型、发送者、内容、图片、间隔时间与排序操作。 */
export function MessageList({ participants, messages, sessionId, onChange }: MessageListProps) {
  const textareaRefs = useRef<Map<number, HTMLTextAreaElement>>(new Map());
  const [openEmojiIndex, setOpenEmojiIndex] = useState<number | null>(null);

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
    if (participants.length === 0) {
      // 还没有参与者时,先默认新增一条系统消息(不依赖 sender_id)
      onChange([
        ...messages,
        {
          sender_id: SYSTEM_ID,
          kind: 'sys',
          text: '',
          image_url: null,
          video_url: null,
          cover_url: null,
          duration: null,
          delay_ms: 1500,
          align: null,
        },
      ]);
      return;
    }
    const sender = participants[0].id;
    onChange([
      ...messages,
      {
        sender_id: sender,
        kind: 'text',
        text: '',
        image_url: null,
        video_url: null,
        cover_url: null,
        duration: null,
        delay_ms: 1500,
        align: null,
      },
    ]);
  };

  const insertEmoji = (index: number, emoji: string) => {
    const textarea = textareaRefs.current.get(index);
    if (!textarea) return;
    const start = textarea.selectionStart ?? 0;
    const end = textarea.selectionEnd ?? 0;
    const current = messages[index].text ?? '';
    const nextText = current.slice(0, start) + emoji + current.slice(end);
    updateAt(index, { text: nextText });
    // 保持焦点并移动光标到插入位置之后
    // selectionStart/End 以 UTF-16 code unit 计数,因此使用 emoji.length
    requestAnimationFrame(() => {
      textarea.focus();
      const pos = start + emoji.length;
      textarea.setSelectionRange(pos, pos);
    });
  };

  const toggleEmojiPanel = (index: number) => {
    setOpenEmojiIndex((prev) => (prev === index ? null : index));
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
                    // 切换类型时,同步修正 sender_id:
                    // - 切到 sys:固定为 SYSTEM_ID
                    // - 切到非 sys 且当前 sender_id 仍是 SYSTEM_ID:挑一个有效参与者,
                    //   否则后端会因 '__system__' 不在参与者列表里而拒绝
                    let senderId: string;
                    if (kind === 'sys') {
                      senderId = SYSTEM_ID;
                    } else if (m.sender_id === SYSTEM_ID) {
                      senderId = participants[0]?.id ?? '';
                    } else {
                      senderId = m.sender_id;
                    }
                    updateAt(i, { kind, sender_id: senderId });
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
                <select
                  className="align-select"
                  value={m.align ?? 'auto'}
                  disabled={isSys || m.kind === 'timestamp'}
                  onChange={(e) => {
                    const v = e.target.value as 'auto' | 'left' | 'right';
                    updateAt(i, { align: v === 'auto' ? null : v });
                  }}
                >
                  {ALIGN_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="message-text-field">
                <textarea
                  ref={(el) => {
                    if (el) textareaRefs.current.set(i, el);
                    else textareaRefs.current.delete(i);
                  }}
                  className="message-text"
                  rows={2}
                  maxLength={500}
                  placeholder={
                    isSys ? '系统消息内容' : m.kind === 'image' ? '图片说明（可选）' : '消息内容'
                  }
                  value={m.text ?? ''}
                  onChange={(e) => updateAt(i, { text: e.target.value })}
                />
                <div className="message-text-tools">
                  <button
                    type="button"
                    className={`btn btn-sm emoji-toggle${openEmojiIndex === i ? ' emoji-toggle--active' : ''}`}
                    onClick={() => toggleEmojiPanel(i)}
                  >
                    😊 表情
                  </button>
                </div>
              </div>
              {openEmojiIndex === i && (
                <div className="emoji-panel">
                  {DEFAULT_EMOJIS.map((emoji) => (
                    <button
                      key={emoji}
                      type="button"
                      className="emoji-option"
                      onClick={() => insertEmoji(i, emoji)}
                      title={emoji}
                    >
                      {emoji}
                    </button>
                  ))}
                </div>
              )}
              {m.kind === 'image' && (
                <div className="message-image-row">
                  <AvatarPicker
                    kind="image"
                    value={m.image_url}
                    onChange={(url) => updateAt(i, { image_url: url })}
                    alt="消息图片"
                    sessionId={sessionId}
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
