import { useCallback, useState } from 'react';
import { submitRender } from './api';
import type { ChatConfig, Message, Participant } from './types';
import { validateConfig } from './validate';
import { HeaderEditor } from './components/HeaderEditor';
import { StatusBarEditor } from './components/StatusBarEditor';
import { ParticipantList } from './components/ParticipantList';
import { MessageList } from './components/MessageList';
import { PreviewPanel } from './components/PreviewPanel';
import { ProgressPanel } from './components/ProgressPanel';

const SYSTEM_ID = '__system__';

function createDefaultConfig(): ChatConfig {
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

export default function App() {
  const [config, setConfig] = useState<ChatConfig>(createDefaultConfig);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const updateHeader = useCallback(
    (patch: {
      mode?: ChatConfig['mode'];
      title?: string;
      background?: string;
      background_image_url?: string | null;
    }) => {
      setConfig((prev) => ({ ...prev, ...patch }));
    },
    [],
  );

  const updateStatusBar = useCallback(
    (patch: Partial<ChatConfig['status_bar']>) => {
      setConfig((prev) => ({
        ...prev,
        status_bar: { ...prev.status_bar, ...patch },
      }));
    },
    [],
  );

  const updateParticipants = useCallback((participants: Participant[]) => {
    setConfig((prev) => {
      const ids = new Set(participants.map((p) => p.id));
      // 同步清理已被删除参与者的消息，避免出现悬空 sender_id
      const messages = prev.messages.filter(
        (m) => m.sender_id === SYSTEM_ID || ids.has(m.sender_id),
      );
      return { ...prev, participants, messages };
    });
  }, []);

  const updateMessages = useCallback((messages: Message[]) => {
    setConfig((prev) => ({ ...prev, messages }));
  }, []);

  const handleRender = async () => {
    const problem = validateConfig(config);
    if (problem) {
      setSubmitError(problem);
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      const id = await submitRender(config);
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
            mode={config.mode}
            title={config.title}
            background={config.background}
            backgroundImage={config.background_image_url}
            onChange={updateHeader}
          />
          <StatusBarEditor statusBar={config.status_bar} onChange={updateStatusBar} />
          <ParticipantList
            participants={config.participants}
            mode={config.mode}
            onChange={updateParticipants}
          />
          <MessageList
            participants={config.participants}
            messages={config.messages}
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
          <PreviewPanel config={config} />
          <ProgressPanel jobId={jobId} />
        </div>
      </main>
    </div>
  );
}
