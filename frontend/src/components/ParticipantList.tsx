import type { Mode, Participant } from '../types';
import { AvatarPicker } from './common/AvatarPicker';

interface ParticipantListProps {
  participants: Participant[];
  mode: Mode;
  sessionId: string | null;
  onChange: (participants: Participant[]) => void;
}

/** 生成不冲突的参与者 id，形如 p1、p2 … */
function nextParticipantId(participants: Participant[]): string {
  let n = 1;
  const used = new Set(participants.map((p) => p.id));
  while (used.has(`p${n}`)) {
    n += 1;
  }
  return `p${n}`;
}

/** 参与者列表：名称、头像上传、删除与新增。 */
export function ParticipantList({ participants, mode, sessionId, onChange }: ParticipantListProps) {
  const updateAt = (index: number, patch: Partial<Participant>) => {
    onChange(participants.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  };

  const removeAt = (index: number) => {
    if (participants.length <= 2) return;
    onChange(participants.filter((_, i) => i !== index));
  };

  const addParticipant = () => {
    const id = nextParticipantId(participants);
    onChange([...participants, { id, name: '', avatar_url: null, label: null }]);
  };

  return (
    <section className="card">
      <h2 className="card-title">参与者（{participants.length}）</h2>
      {mode === 'single' && (
        <p className="hint">第一个参与者视为「我」，其发言显示在右侧。</p>
      )}
      <ul className="participant-list">
        {participants.map((p, i) => (
          <li key={p.id} className="participant-row">
            <AvatarPicker
              value={p.avatar_url}
              onChange={(url) => updateAt(i, { avatar_url: url })}
              alt={`${p.name || '参与者'} 的头像`}
              sessionId={sessionId}
            />
            <input
              type="text"
              className="participant-name"
              maxLength={16}
              placeholder={`参与者 ${i + 1} 名称`}
              value={p.name}
              onChange={(e) => updateAt(i, { name: e.target.value })}
            />
            <span className="participant-id" title="参与者 ID">
              {p.id}
            </span>
            <button
              type="button"
              className="btn btn-sm btn-danger"
              disabled={participants.length <= 2}
              onClick={() => removeAt(i)}
            >
              删除
            </button>
          </li>
        ))}
      </ul>
      <button type="button" className="btn btn-ghost" onClick={addParticipant}>
        添加参与者
      </button>
    </section>
  );
}
