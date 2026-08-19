import { useCallback, useEffect, useMemo, useState } from 'react';
import { createSession, submitRender } from './api';
import type { ChatScene, Message, Participant, VideoDSL } from './types';
import { validateConfig } from './validate';
import { HeaderEditor } from './components/HeaderEditor';
import { StatusBarEditor } from './components/StatusBarEditor';
import { ParticipantList } from './components/ParticipantList';
import { MessageList } from './components/MessageList';
import { PreviewPanel } from './components/PreviewPanel';
import { ProgressPanel } from './components/ProgressPanel';
import { StaticPreview } from './components/StaticPreview';
import { SummaryStep } from './components/SummaryStep';
import { WizardLayout, type WizardStep } from './components/WizardLayout';

const SYSTEM_ID = '__system__';
const TOTAL_STEPS = 5;

const STEPS: WizardStep[] = [
  { id: 1, title: '基本信息' },
  { id: 2, title: '状态栏' },
  { id: 3, title: '参与人' },
  { id: 4, title: '消息内容' },
  { id: 5, title: '预览生成' },
];

/** 默认状态栏配置 —— 与参考图保持一致，全图标打开 + 常见数值。 */
export const DEFAULT_STATUS_BAR: ChatScene['status_bar'] = {
  time: '12:34',
  battery_level: 61,
  signal_type: '5G',
  signal_type_secondary: '5G',
  dual_sim: true,
  show_wifi: true,
  show_signal: true,
  show_bluetooth: true,
  show_alarm: true,
};

function createDefaultScene(): ChatScene {
  return {
    mode: 'group',
    title: '群聊',
    subtitle: null,
    background: '#ededed',
    background_image_url: null,
    duration_ms: null,
    opacity: 1,
    status_bar: { ...DEFAULT_STATUS_BAR },
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

/**
 * 每步最低校验：通过则允许「下一步」，并在底部显示「该步已就绪」。
 * 复用 validateConfig 的中文错误文案，保持前后端校验一致。
 */
function getStepError(step: number, scene: ChatScene): string | null {
  switch (step) {
    case 1:
      return scene.title?.trim() ? null : '聊天标题不能为空';
    case 2:
      return null;
    case 3:
      return scene.participants.length >= 2 ? null : '至少需要 2 名参与者';
    case 4: {
      if (scene.messages.length < 1) {
        return '至少需要 1 条消息';
      }
      const participantIds = new Set(scene.participants.map((p) => p.id));
      for (const m of scene.messages) {
        if (m.kind === 'sys' || m.kind === 'text') {
          if (!m.text || m.text.trim() === '') {
            return m.kind === 'sys' ? '系统消息需要填写文本内容' : '文字消息需要填写文本内容';
          }
        } else if (m.kind === 'image' && !m.image_url) {
          return '图片消息需要上传图片';
        }
        if (m.kind !== 'sys' && m.kind !== 'timestamp' && !participantIds.has(m.sender_id)) {
          return '消息发送者必须是已添加的参与者';
        }
        if (m.delay_ms < 100 || m.delay_ms > 60000) {
          return '消息间隔需在 100–60000ms 之间';
        }
      }
      if (scene.messages[0].delay_ms < 500) {
        return '第一条消息的间隔至少 500ms';
      }
      return null;
    }
    case 5:
      return validateConfig(scene);
    default:
      return null;
  }
}

export default function App() {
  const [dsl, setDsl] = useState<VideoDSL>(createDefaultDSL);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(1);
  // 当前任务所在的 session;前端启动时调一次 /api/sessions 拿到。
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // 进入页面即建一个新 session;失败时把错误显示在底部,功能仍可浏览但上传/渲染受限。
  useEffect(() => {
    let cancelled = false;
    createSession()
      .then((s) => {
        if (cancelled) return;
        setSessionId(s.id);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setSessionError(err instanceof Error ? err.message : '创建会话失败');
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    if (!sessionId) {
      setSubmitError(sessionError ?? '会话未就绪，无法提交');
      return;
    }
    const problem = validateConfig(dsl.scene);
    if (problem) {
      setSubmitError(problem);
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      const id = await submitRender(dsl, sessionId);
      setJobId(id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '提交渲染任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  const stepError = useMemo(
    () => getStepError(currentStep, dsl.scene),
    [currentStep, dsl.scene],
  );
  const hint = stepError ? { ok: false, text: stepError } : { ok: true, text: '该步已就绪' };

  const form = (() => {
    switch (currentStep) {
      case 1:
        return (
          <HeaderEditor
            mode={dsl.scene.mode}
            title={dsl.scene.title}
            backgroundImage={dsl.scene.background_image_url}
            opacity={dsl.scene.opacity}
            sessionId={sessionId}
            onChange={updateScene}
          />
        );
      case 2:
        return <StatusBarEditor statusBar={dsl.scene.status_bar} onChange={updateStatusBar} />;
      case 3:
        return (
          <ParticipantList
            participants={dsl.scene.participants}
            mode={dsl.scene.mode}
            sessionId={sessionId}
            onChange={updateParticipants}
          />
        );
      case 4:
        return (
          <MessageList
            participants={dsl.scene.participants}
            messages={dsl.scene.messages}
            sessionId={sessionId}
            onChange={updateMessages}
          />
        );
      case 5:
        return (
          <>
            <SummaryStep scene={dsl.scene} />
            {sessionError && <div className="error-banner">会话初始化失败: {sessionError}</div>}
            {submitError && <div className="error-banner">{submitError}</div>}
          </>
        );
      default:
        return null;
    }
  })();

  return (
    <div className="app">
      <header className="app-header">
        <h1>微信聊天视频生成器</h1>
        <span className="app-header-sub">
          配置聊天内容，一键生成视频
          {sessionId && <code className="session-tag">session: {sessionId.slice(0, 8)}…</code>}
        </span>
      </header>
      <WizardLayout
        steps={STEPS}
        currentStep={currentStep}
        onStepClick={setCurrentStep}
        form={form}
        preview={
          currentStep === TOTAL_STEPS ? (
            <PreviewPanel dsl={dsl} sessionId={sessionId} />
          ) : (
            <StaticPreview step={currentStep as 1 | 2 | 3 | 4} scene={dsl.scene} />
          )
        }
        extraPreview={currentStep === TOTAL_STEPS ? <ProgressPanel jobId={jobId} /> : null}
        hint={hint}
        footerLeft={
          <button
            type="button"
            className="btn"
            disabled={currentStep === 1}
            onClick={() => setCurrentStep((s) => Math.max(1, s - 1))}
          >
            上一步
          </button>
        }
        footerRight={
          currentStep === TOTAL_STEPS ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={submitting || !!stepError || !sessionId}
              onClick={() => void handleRender()}
            >
              {submitting ? '提交中…' : '生成视频'}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={!!stepError}
              onClick={() => setCurrentStep((s) => Math.min(TOTAL_STEPS, s + 1))}
            >
              下一步
            </button>
          )
        }
      />
    </div>
  );
}