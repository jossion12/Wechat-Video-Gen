import { validateConfig } from './validate.ts';
import type { ChatScene } from './types.ts';

function buildScene(messages: ChatScene['messages']): ChatScene {
  return {
    mode: 'single',
    title: '测试',
    background: '#ffffff',
    background_image_url: null,
    duration_ms: null,
    opacity: 1,
    style_theme: 'comic',
    intent: 'short_video_drama',
    intent_acknowledged: true,
    participants: [
      { id: 'me', name: '我', avatar_url: null, persona: null },
      { id: 'her', name: '她', avatar_url: null, persona: null },
    ],
    messages,
    watermark: { text: '本内容由 AI 生成 · 仅供创意表达', badge_style: 'neon' },
  };
}

function makeText(text: string, replyTo: number | null = null) {
  return {
    sender_id: 'me' as const,
    kind: 'text' as const,
    text,
    image_url: null,
    video_url: null,
    cover_url: null,
    duration: null,
    delay_ms: 1500,
    align: null,
    reply_to: replyTo,
  };
}

function assertPass(label: string, scene: ChatScene) {
  const err = validateConfig(scene);
  if (err !== null) {
    throw new Error(`${label}: expected pass but got: ${err}`);
  }
}

function assertFail(label: string, scene: ChatScene) {
  const err = validateConfig(scene);
  if (err === null) {
    throw new Error(`${label}: expected fail but passed`);
  }
}

// messages[2].reply_to = 1 → 指向第一条消息，合法
assertPass(
  'reply to earlier message',
  buildScene([makeText('first'), makeText('second'), makeText('third', 1)]),
);

// messages[1]（1-based 的第一条消息）.reply_to = 1 → 指向自己，非法
assertFail(
  'reply to self',
  buildScene([makeText('first', 1), makeText('second')]),
);

// 指向 sys 消息，非法
assertFail(
  'reply to sys message',
  buildScene([
    { sender_id: '__system__', kind: 'sys', text: '幕间', image_url: null, video_url: null, cover_url: null, duration: null, delay_ms: 1500, align: null, reply_to: null },
    makeText('reply to sys', 1),
  ]),
);

// 越界，非法
assertFail(
  'reply out of range',
  buildScene([makeText('only'), makeText('reply out', 5)]),
);

console.log('validate.test.ts: all passed');
