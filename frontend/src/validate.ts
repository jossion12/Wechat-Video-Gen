import type { ChatScene, Intent } from './types';

function containsPlatformName(text: string, name: string): boolean {
  // 中文平台名按子串匹配;英文平台名按单词边界匹配,
  // 避免 "Meta" 误杀 "Metal" 等技术词汇。
  if (/[\u4e00-\u9fa5]/.test(name)) {
    return text.includes(name);
  }
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`\\b${escaped}\\b`).test(text);
}

// 与服务端 HIGH_RISK_WORDS / PLATFORM_NAMES 保持一致
const HIGH_RISK_WORDS = [
  '转账', '红包', '密码', '验证码', '银行卡', '汇款', '借款',
  '信用卡', '借记卡', '账户余额', '支付密码', '登录密码',
];

const PLATFORM_NAMES = [
  '微信', 'WeChat', 'WhatsApp', '腾讯', 'Tencent', 'Meta', 'Facebook',
  'Messenger', 'Line', 'Telegram', '钉钉', '飞书', 'Slack',
];

const ALLOWED_INTENTS: Intent[] = [
  'short_video_drama',
  'story_visualization',
  'teaching_simulation',
  'meme_sticker',
];

/**
 * 与服务端 models.py 校验对齐的客户端预校验。
 * 返回 null 表示通过;否则返回面向用户的中文提示。
 */
export function validateConfig(config: ChatScene): string | null {
  if (!config.intent || !ALLOWED_INTENTS.includes(config.intent)) {
    return '请选择一个创作意图';
  }
  if (!config.intent_acknowledged) {
    return '请阅读并同意合规使用承诺';
  }
  if (config.mode === 'single' && config.participants.length !== 2) {
    return '对谈模式需要恰好 2 名角色';
  }
  if (config.participants.length < 2) {
    return '至少需要 2 名参与者';
  }
  if (config.messages.length < 1) {
    return '至少需要 1 条消息';
  }
  if (!config.title || config.title.trim() === '') {
    return '标题不能为空';
  }
  const participantIds = new Set(config.participants.map((p) => p.id));
  for (let i = 0; i < config.messages.length; i++) {
    const m = config.messages[i];
    if (m.kind === 'sys' || m.kind === 'text') {
      if (!m.text || m.text.trim() === '') {
        return m.kind === 'sys' ? '系统消息需要填写文本内容' : '文字消息需要填写文本内容';
      }
    } else if (m.kind === 'image' && !m.image_url) {
      return '图片消息需要上传图片';
    }
    if (
      m.kind !== 'sys' &&
      m.kind !== 'timestamp' &&
      !participantIds.has(m.sender_id)
    ) {
      return '消息发送者必须是已添加的参与者';
    }
    if (m.delay_ms < 100 || m.delay_ms > 60000) {
      return '消息间隔需在 100–60000ms 之间';
    }
    if (m.reply_to != null) {
      const targetIndex = m.reply_to - 1;
      if (
        targetIndex < 0 ||
        targetIndex >= config.messages.length ||
        targetIndex >= i ||
        config.messages[targetIndex].kind === 'sys' ||
        config.messages[targetIndex].kind === 'timestamp'
      ) {
        return `第 ${i + 1} 条消息的引用目标无效`;
      }
    }
    const text = m.text || '';
    for (const word of HIGH_RISK_WORDS) {
      if (text.includes(word)) {
        return `检测到高风险内容「${word}」，请确保仅用于合法创作场景`;
      }
    }
    for (const name of PLATFORM_NAMES) {
      if (containsPlatformName(text, name)) {
        return `请勿模仿真实平台「${name}」，请使用原创表达`;
      }
    }
  }
  if (config.messages[0].delay_ms < 500) {
    return '第一条消息的间隔至少 500ms';
  }
  return null;
}
