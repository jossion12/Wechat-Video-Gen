import type { ChatScene } from './types';

/**
 * 与服务端 models.py 校验对齐的客户端预校验。
 * 返回 null 表示通过;否则返回面向用户的中文提示。
 * 预览与渲染共用,保证不完整的配置不会打到后端产生 422。
 */
export function validateConfig(config: ChatScene): string | null {
  if (config.participants.length < 2) {
    return '至少需要 2 名参与者';
  }
  if (config.messages.length < 1) {
    return '至少需要 1 条消息';
  }
  if (!config.title || config.title.trim() === '') {
    return '聊天标题不能为空';
  }
  const participantIds = new Set(config.participants.map((p) => p.id));
  for (const m of config.messages) {
    if (m.kind === 'sys' || m.kind === 'text') {
      if (!m.text || m.text.trim() === '') {
        return m.kind === 'sys' ? '系统消息需要填写文本内容' : '文字消息需要填写文本内容';
      }
    } else if (m.kind === 'image' && !m.image_url) {
      return '图片消息需要上传图片';
    }
    // 非系统/时间戳消息的发送者必须对应一个真实参与者,否则后端会 422
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
  }
  if (config.messages[0].delay_ms < 500) {
    return '第一条消息的间隔至少 500ms';
  }
  return null;
}
