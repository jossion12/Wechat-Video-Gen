import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createSession, importZip, submitRender } from './api';
import type { ChatScene, Message, Participant, VideoDSL } from './types';
import { THEME_DEFAULT_BACKGROUND } from './types';
import { validateConfig } from './validate';
import { HeaderEditor } from './components/HeaderEditor';
import { IntentStep } from './components/IntentStep';
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
  { id: 1, title: '创作意图' },
  { id: 2, title: '视觉风格' },
  { id: 3, title: '角色设定' },
  { id: 4, title: '消息内容' },
  { id: 5, title: '预览生成' },
];

function createDefaultScene(): ChatScene {
  return {
    mode: 'group',
    title: '对话剧场',
    background: THEME_DEFAULT_BACKGROUND.comic,
    background_image_url: null,
    duration_ms: null,
    opacity: 1,
    style_theme: 'comic',
    intent: 'short_video_drama',
    intent_acknowledged: false,
    participants: [],
    messages: [],
    watermark: { text: '本内容由 AI 生成 · 仅供创意表达', badge_style: 'neon' },
  };
}

function createDefaultDSL(): VideoDSL {
  return {
    schema_version: '1.0',
    kind: 'chat',
    template: 'cyberpunk',
    scene: createDefaultScene(),
  };
}

function sanitizeMessages(messages: Message[]): Message[] {
  return messages.map((m, i) => {
    if (m.reply_to == null) return m;
    const targetIndex = m.reply_to - 1;
    if (
      targetIndex < 0 ||
      targetIndex >= messages.length ||
      targetIndex >= i ||
      messages[targetIndex].kind === 'sys' ||
      messages[targetIndex].kind === 'timestamp'
    ) {
      return { ...m, reply_to: null };
    }
    return m;
  });
}

/**
 * 每步最低校验：通过则允许「下一步」，并在底部显示「该步已就绪」。
 */
function getStepError(step: number, scene: ChatScene): string | null {
  switch (step) {
    case 1: {
      if (!scene.intent) return '请选择一个创作意图';
      if (!scene.intent_acknowledged) return '请阅读并同意合规使用承诺';
      return null;
    }
    case 2:
      return scene.title?.trim() ? null : '标题不能为空';
    case 3: {
      if (scene.mode === 'single' && scene.participants.length !== 2) {
        return '对谈模式需要恰好 2 名角色';
      }
      return scene.participants.length >= 2 ? null : '至少需要 2 名角色';
    }
    case 4: {
      if (scene.messages.length < 1) {
        return '至少需要 1 条消息';
      }
      const participantIds = new Set(scene.participants.map((p) => p.id));
      for (let i = 0; i < scene.messages.length; i++) {
        const m = scene.messages[i];
        if (m.kind === 'sys' || m.kind === 'text') {
          if (!m.text || m.text.trim() === '') {
            return m.kind === 'sys' ? '系统消息需要填写文本内容' : '文字消息需要填写文本内容';
          }
        } else if (m.kind === 'image' && !m.image_url) {
          return '图片消息需要上传图片';
        }
        if (m.kind !== 'sys' && m.kind !== 'timestamp' && !participantIds.has(m.sender_id)) {
          return '消息发送者必须是已添加的角色';
        }
        if (m.delay_ms < 100 || m.delay_ms > 60000) {
          return '消息间隔需在 100–60000ms 之间';
        }
        if (m.reply_to != null) {
          const targetIndex = m.reply_to - 1;
          if (
            targetIndex < 0 ||
            targetIndex >= scene.messages.length ||
            targetIndex >= i ||
            scene.messages[targetIndex].kind === 'sys' ||
            scene.messages[targetIndex].kind === 'timestamp'
          ) {
            return `第 ${i + 1} 条消息的引用目标无效`;
          }
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
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);

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
    setDsl((prev) => {
      let nextScene = { ...prev.scene, ...patch };
      // 从群像切换为对谈时，角色数限制为 2，并移除引用被删除角色的消息
      if (patch.mode === 'single' && prev.scene.participants.length > 2) {
        const kept = prev.scene.participants.slice(0, 2);
        const keptIds = new Set(kept.map((p) => p.id));
        const messages = sanitizeMessages(
          prev.scene.messages.filter(
            (m) => m.sender_id === SYSTEM_ID || keptIds.has(m.sender_id),
          ),
        );
        nextScene = { ...nextScene, participants: kept, messages };
      }
      // 风格切换时保持 DSL template 与 scene.style_theme 一致，并自动切换到该主题的推荐背景色
      const nextTemplate = patch.style_theme ?? nextScene.style_theme;
      if (patch.style_theme && patch.style_theme !== prev.scene.style_theme) {
        nextScene = {
          ...nextScene,
          background: THEME_DEFAULT_BACKGROUND[patch.style_theme],
        };
      }
      return { ...prev, template: nextTemplate as VideoDSL['template'], scene: nextScene };
    });
  }, []);

  const updateParticipants = useCallback((participants: Participant[]) => {
    setDsl((prev) => {
      const ids = new Set(participants.map((p) => p.id));
      const messages = sanitizeMessages(
        prev.scene.messages.filter(
          (m) => m.sender_id === SYSTEM_ID || ids.has(m.sender_id),
        ),
      );
      return { ...prev, scene: { ...prev.scene, participants, messages } };
    });
  }, []);

  const updateMessages = useCallback((messages: Message[]) => {
    setDsl((prev) => ({
      ...prev,
      scene: { ...prev.scene, messages: sanitizeMessages(messages) },
    }));
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

  const handleImportFile = useCallback(
    async (file: File) => {
      if (!sessionId) {
        setImportError('会话未就绪，无法导入');
        return;
      }
      if (!file.name.toLowerCase().endsWith('.zip')) {
        setImportError('仅支持 .zip 文件');
        return;
      }
      setImporting(true);
      setImportError(null);
      try {
        const result = await importZip(file, sessionId);
        setDsl(result.dsl);
        setJobId(null);
        setCurrentStep(5);
      } catch (err) {
        setImportError(err instanceof Error ? err.message : '导入失败');
      } finally {
        setImporting(false);
      }
    },
    [sessionId],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (importing) return;
      const file = e.dataTransfer.files?.[0];
      if (file) handleImportFile(file);
    },
    [handleImportFile, importing],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const stepError = useMemo(
    () => getStepError(currentStep, dsl.scene),
    [currentStep, dsl.scene],
  );
  const hint = stepError ? { ok: false, text: stepError } : { ok: true, text: '该步已就绪' };

  const form = (() => {
    switch (currentStep) {
      case 1:
        return (
          <IntentStep
            intent={dsl.scene.intent}
            acknowledged={dsl.scene.intent_acknowledged}
            onChange={updateScene}
          />
        );
      case 2:
        return (
          <HeaderEditor
            mode={dsl.scene.mode}
            title={dsl.scene.title}
            backgroundImage={dsl.scene.background_image_url}
            opacity={dsl.scene.opacity}
            styleTheme={dsl.scene.style_theme}
            watermark={dsl.scene.watermark}
            sessionId={sessionId}
            onChange={updateScene}
          />
        );
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
        <h1>对话剧场 / Dialogue Theater</h1>
        <span className="app-header-sub">
          用对话形式讲述你的故事
          {sessionId && <code className="session-tag">session: {sessionId.slice(0, 8)}…</code>}
        </span>
        <input
          type="file"
          accept=".zip"
          ref={importInputRef}
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleImportFile(file);
            e.target.value = '';
          }}
        />
        <button
          type="button"
          className="btn"
          disabled={importing || !sessionId}
          onClick={() => importInputRef.current?.click()}
        >
          {importing ? '导入中…' : '导入 zip'}
        </button>
      </header>
      {importError && <div className="error-banner">{importError}</div>}
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
        className={dragOver ? 'wizard-layout--dragover' : undefined}
        style={importing ? { pointerEvents: 'none', opacity: 0.6 } : undefined}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        footerLeft={
          <button
            type="button"
            className="btn"
            disabled={currentStep === 1 || importing}
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
              disabled={submitting || !!stepError || !sessionId || importing}
              onClick={() => void handleRender()}
            >
              {submitting ? '提交中…' : '生成视频'}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={!!stepError || importing}
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
