import { useCallback, useState } from 'react';
import { submitRender } from './api';
import type { ChatScene, Message, Participant, VideoDSL } from './types';
import { validateConfig } from './validate';
import { HeaderEditor } from './components/HeaderEditor';
import { StatusBarEditor } from './components/StatusBarEditor';
import { ParticipantList } from './components/ParticipantList';
import { MessageList } from './components/MessageList';
import { PreviewPanel } from './components/PreviewPanel';
import { ProgressPanel } from './components/ProgressPanel';

const SYSTEM_ID = '__system__';

function createDefaultScene(): ChatScene {
  return {
    mode: 'group',
    title: '群聊',
    subtitle: null,
    background: '#ededed',
    background_image_url: null,
    duration_ms: null,
    status_bar: {
      time: '12:34',
      battery_level: 100,
      network_speed: null,
      signal_type: null,
      signal_type_secondary: null,
      dual_sim: false,
      show_wifi: true,
      show_signal: true,
      show_bluetooth: false,
      show_alarm: false,
      show_nfc: false,
      app_icons: [],
    },
    member_count: null,
    muted: false,
    participants: [],
    messages: [],
  };
}

function createDefaultDSL(): VideoDSL {
  return {
    schema_version: '1.0',
    kind: 'chat',
    template: 'wechat',
    scene: createDefaultScene(),
  };
}

export default function App() {
  const [dsl, setDsl] = useState<VideoDSL>(createDefaultDSL);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const updateScene = useCallback((patch: Partial<ChatScene>) => {
    setDsl((prev) => ({ ...prev, scene: { ...prev.scene, ...patch } }));
  }, []);

  const updateStatusBar = useCallback(
    (patch: Partial<ChatScene['status_bar']>) => {
      setDsl((prev) => ({
        ...prev,
        scene: { ...prev.scene, status_bar: { ...prev.scene.status_bar, ...patch } },
      }));
    },
    [],
  );

  const updateParticipants = useCallback((participants: Participant[]) => {
    setDsl((prev) => {
      const ids = new Set(participants.map((p) => p.id));
      // 同步清理已被删除参与者的消息，避免出现悬空 sender_id
      const messages = prev.scene.messages.filter(
        (m) => m.sender_id === SYSTEM_ID || ids.has(m.sender_id),
      );
      return { ...prev, scene: { ...prev.scene, participants, messages } };
    });
  }, []);

  const updateMessages = useCallback((messages: Message[]) => {
    setDsl((prev) => ({ ...prev, scene: { ...prev.scene, messages } }));
  }, []);

  const handleRender = async () => {
    const problem = validateConfig(dsl.scene);
    if (problem) {
      setSubmitError(problem);
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      const id = await submitRender(dsl);
      setJobId(id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '提交渲染任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>微信聊天视频生成器</h1>
        <span className="app-header-sub">配置聊天内容，一键生成视频</span>
      </header>
      <main className="app-main">
        <div className="left-column">
          <HeaderEditor
            mode={dsl.scene.mode}
            title={dsl.scene.title}
            background={dsl.scene.background}
            backgroundImage={dsl.scene.background_image_url}
            onChange={updateScene}
          />
          <StatusBarEditor statusBar={dsl.scene.status_bar} onChange={updateStatusBar} />
          <ParticipantList
            participants={dsl.scene.participants}
            mode={dsl.scene.mode}
            onChange={updateParticipants}
          />
          <MessageList
            participants={dsl.scene.participants}
            messages={dsl.scene.messages}
            onChange={updateMessages}
          />
          <div className="card submit-card">
            {submitError && <div className="error-banner">{submitError}</div>}
            <button
              type="button"
              className="btn btn-primary btn-block"
              disabled={submitting}
              onClick={() => void handleRender()}
            >
              {submitting ? '提交中…' : '生成视频'}
            </button>
          </div>
        </div>
        <div className="right-column">
          <PreviewPanel dsl={dsl} />
          <ProgressPanel jobId={jobId} />
        </div>
      </main>
    </div>
  );
}
