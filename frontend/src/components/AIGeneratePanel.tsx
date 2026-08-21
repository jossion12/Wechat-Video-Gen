import { useEffect, useMemo, useState } from 'react';
import { continueDialogue, generateDialogue, getAIQuota } from '../api';
import type { ChatScene, Message, VideoDSL } from '../types';
import { INTENT_LABELS, STYLE_THEME_LABELS } from '../types';

type Tab = 'generate' | 'continue';

interface AIGeneratePanelProps {
  sessionId: string | null;
  scene: ChatScene;
  dsl: VideoDSL;
  onApplyGenerated: (dsl: VideoDSL) => void;
  onAppendCandidates: (candidates: Message[]) => void;
}

const MIN_SYNOPSIS_LEN = 10;

export function AIGeneratePanel({
  sessionId,
  scene,
  dsl,
  onApplyGenerated,
  onAppendCandidates,
}: AIGeneratePanelProps) {
  const [tab, setTab] = useState<Tab>('generate');
  const [synopsis, setSynopsis] = useState('');
  const [numMessages, setNumMessages] = useState(8);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ daily_limit: number; used_today: number; remaining_today: number } | null>(null);
  const [generatedDSL, setGeneratedDSL] = useState<VideoDSL | null>(null);
  const [candidates, setCandidates] = useState<Message[] | null>(null);

  const canGenerate = useMemo(
    () => !!sessionId && synopsis.trim().length >= MIN_SYNOPSIS_LEN && numMessages >= 2 && numMessages <= 20,
    [sessionId, synopsis, numMessages],
  );

  const canContinue = useMemo(
    () => !!sessionId && scene.messages.length > 0,
    [sessionId, scene.messages.length],
  );

  useEffect(() => {
    let cancelled = false;
    getAIQuota()
      .then((q) => {
        if (!cancelled) setQuota(q);
      })
      .catch(() => {
        // quota 非关键,失败不阻塞
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshQuota = async () => {
    try {
      setQuota(await getAIQuota());
    } catch {
      // ignore
    }
  };

  const handleGenerate = async () => {
    if (!sessionId || !canGenerate) return;
    setLoading(true);
    setError(null);
    setGeneratedDSL(null);
    setCandidates(null);
    try {
      const result = await generateDialogue({
        session_id: sessionId,
        synopsis: synopsis.trim(),
        mode: scene.mode,
        style_theme: scene.style_theme,
        intent: scene.intent,
        num_messages: numMessages,
      });
      setGeneratedDSL(result);
      await refreshQuota();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 生成失败');
    } finally {
      setLoading(false);
    }
  };

  const handleContinue = async () => {
    if (!sessionId || !canContinue) return;
    setLoading(true);
    setError(null);
    setGeneratedDSL(null);
    setCandidates(null);
    try {
      const result = await continueDialogue({
        session_id: sessionId,
        dsl,
        num_candidates: 3,
      });
      setCandidates(result);
      await refreshQuota();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 续写失败');
    } finally {
      setLoading(false);
    }
  };

  const applyGenerated = () => {
    if (generatedDSL) {
      onApplyGenerated(generatedDSL);
      setGeneratedDSL(null);
      setSynopsis('');
    }
  };

  const applyCandidates = () => {
    if (candidates && candidates.length > 0) {
      onAppendCandidates(candidates);
      setCandidates(null);
    }
  };

  const quotaText = quota
    ? quota.remaining_today >= 0
      ? `今日剩余 ${quota.remaining_today}/${quota.daily_limit} 次`
      : 'AI 生成未限制额度'
    : '';

  return (
    <section className="card ai-generate-panel">
      <h2 className="card-title">
        AI 辅助创作
        {quotaText && <span className="ai-quota">{quotaText}</span>}
      </h2>

      <div className="ai-tabs">
        <button
          type="button"
          className={`btn btn-sm ${tab === 'generate' ? 'btn-primary' : ''}`}
          onClick={() => setTab('generate')}
        >
          生成对话
        </button>
        <button
          type="button"
          className={`btn btn-sm ${tab === 'continue' ? 'btn-primary' : ''}`}
          onClick={() => setTab('continue')}
        >
          续写对话
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {tab === 'generate' && (
        <div className="ai-section">
          <p className="hint">
            输入剧情概要，AI 会自动生成角色和消息。当前风格：
            {STYLE_THEME_LABELS[scene.style_theme]}，意图：
            {INTENT_LABELS[scene.intent]}。
          </p>
          <textarea
            className="ai-synopsis"
            rows={5}
            placeholder="例如：两个同事在周五下班前讨论周末团建计划，一个想去爬山，一个想宅家打游戏……"
            value={synopsis}
            onChange={(e) => setSynopsis(e.target.value)}
            maxLength={800}
          />
          <div className="ai-options">
            <label className="ai-option">
              消息数量
              <input
                type="number"
                min={2}
                max={20}
                value={numMessages}
                onChange={(e) => {
                  const v = Number.parseInt(e.target.value, 10);
                  setNumMessages(Number.isNaN(v) ? 8 : Math.max(2, Math.min(20, v)));
                }}
              />
            </label>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canGenerate || loading}
            onClick={() => void handleGenerate()}
          >
            {loading ? '生成中…' : '生成完整对话'}
          </button>

          {generatedDSL && (
            <div className="ai-preview">
              <h3 className="ai-preview-title">生成结果预览</h3>
              <ul className="ai-preview-list">
                <li>标题：{generatedDSL.scene.title}</li>
                <li>
                  角色：
                  {generatedDSL.scene.participants.map((p) => p.name).join('、')}
                </li>
                <li>消息：{generatedDSL.scene.messages.length} 条</li>
              </ul>
              <button type="button" className="btn btn-primary" onClick={applyGenerated}>
                应用生成结果
              </button>
            </div>
          )}
        </div>
      )}

      {tab === 'continue' && (
        <div className="ai-section">
          <p className="hint">基于已有对话上下文，AI 续写 3 条候选消息。</p>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canContinue || loading}
            onClick={() => void handleContinue()}
          >
            {loading ? '续写中…' : 'AI 续写 3 条'}
          </button>

          {candidates && candidates.length > 0 && (
            <div className="ai-preview">
              <h3 className="ai-preview-title">续写候选</h3>
              <ul className="ai-preview-messages">
                {candidates.map((m, i) => (
                  <li key={i} className="ai-preview-message">
                    <span className="ai-preview-sender">
                      {scene.participants.find((p) => p.id === m.sender_id)?.name || m.sender_id}
                    </span>
                    <span className="ai-preview-text">{m.text || `[${m.kind}]`}</span>
                  </li>
                ))}
              </ul>
              <button type="button" className="btn btn-primary" onClick={applyCandidates}>
                追加到消息列表
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
