export type Mode = 'single' | 'group';
export type MessageKind = 'text' | 'image' | 'sys' | 'timestamp' | 'video' | 'emoji';
export type JobStatus = 'queued' | 'running' | 'done' | 'failed';
export type VideoKind = 'chat';
export type VideoTemplate = 'cyberpunk' | 'watercolor' | 'pixel' | 'comic' | 'noir' | 'ink' | 'green_screen';
export type StyleTheme = VideoTemplate;
export type IntroEffect = 'none' | 'scanline' | 'typewriter';
export type Intent =
  | 'short_video_drama'
  | 'story_visualization'
  | 'teaching_simulation'
  | 'meme_sticker';
export type AIBadgeStyle = 'neon' | 'minimal' | 'retro';

// 透明背景产物的封装格式 —— 与后端 VideoDSL.transparent_format 对齐,
// 见 backend/app/recorder.py::render_video_transparent。
export type TransparentFormat = 'webm_vp9_alpha' | 'mov_prores4444';

// 服务端写入 jobs.output_ext 的可能取值,前端用它决定下载按钮文案 / 文件名后缀。
// 'wav' 是 TTS 多角色对话合成(2025-Q3)的产物扩展名,见 backend/app/tts_service.py。
export type OutputExt = 'mp4' | 'webm' | 'mov' | 'wav';

export const INTENT_LABELS: Record<Intent, string> = {
  short_video_drama: '短视频剧情创作',
  story_visualization: '情感故事 / 小说可视化',
  teaching_simulation: '教学演示 / 情景模拟',
  meme_sticker: '表情包 / 梗图制作',
};

export const STYLE_THEME_LABELS: Record<StyleTheme, string> = {
  cyberpunk: '赛博朋克',
  watercolor: '手绘',
  pixel: '复古',
  comic: '漫画',
  noir: '黑白胶片',
  ink: '水墨',
  green_screen: '绿幕',
};

export const INTRO_EFFECT_LABELS: Record<IntroEffect, string> = {
  none: '无特效',
  scanline: '扫描线开场',
  typewriter: '打字机标题',
};

// 透明格式选项下拉框用的中文标签。
export const TRANSPARENT_FORMAT_LABELS: Record<TransparentFormat, string> = {
  webm_vp9_alpha: 'WebM (VP9 + Alpha)',
  mov_prores4444: 'MOV (ProRes 4444)',
};

// 渲染完成后的产物文案 —— 用于下载按钮 / 状态描述。
export const OUTPUT_EXT_LABELS: Record<OutputExt, string> = {
  mp4: 'MP4 (H.264)',
  webm: 'WebM (VP9+Alpha)',
  mov: 'MOV (ProRes 4444)',
  wav: 'WAV (24kHz 单声道)',
};

/** 各主题首次启用时的推荐背景色。 */
export const THEME_DEFAULT_BACKGROUND: Record<StyleTheme, string> = {
  cyberpunk: '#0a0a12',
  watercolor: '#f7f4ed',
  pixel: '#051005',
  comic: '#ffffff',
  noir: '#f5f0e1',
  ink: '#f4ecd8',
  green_screen: '#00ff00',
};

export interface Participant {
  id: string; // unique within config, e.g. 'me', 'alice', 'bob'
  name: string; // display name, ≤16 chars
  avatar_url: string | null; // '/uploads/xxx.png' or null
  persona: string | null; // character profile / personality tags
}

export interface Message {
  sender_id: string; // references Participant.id; '__system__' for sys
  kind: MessageKind;
  text: string | null;
  image_url: string | null; // for kind='image'
  video_url: string | null; // for kind='video'
  cover_url: string | null; // optional video cover
  duration: string | null; // e.g. '0:10' for video
  delay_ms: number; // default 1500
  align: 'left' | 'right' | null; // null = 按旧规则自动推断
  reply_to: number | null; // 回复目标的 1-based 序号;null 表示普通消息
}

export interface WatermarkConfig {
  text: string; // fixed AI generation notice, user cannot edit
  badge_style: AIBadgeStyle; // visual style only, cannot disable
}

/** 对话剧场场景配置。 */
export interface ChatScene {
  mode: Mode; // default 'group'
  title: string; // default '对话剧场'
  background: string; // default '#ffffff'
  background_image_url: string | null; // '/uploads/xxx.png' or null
  background_visible: boolean; // false = 仅显示聊天元素,隐藏背景色/背景图/装饰层
  duration_ms: number | null; // null = auto
  opacity: number; // 0-1, default 1
  intro_effect: IntroEffect; // default 'none'
  style_theme: StyleTheme;
  intent: Intent;
  intent_acknowledged: boolean; // must agree to compliance terms
  participants: Participant[]; // at least 2
  messages: Message[]; // at least 1, ≤100
  watermark: WatermarkConfig;
}

/** 视频生成顶层 DSL。 */
export interface VideoDSL {
  schema_version: '1.0';
  kind: VideoKind;
  template: VideoTemplate; // 'cyberpunk'
  scene: ChatScene;
  // 透明背景输出开关 —— 详见 docs/09-how-to-make-package.md §4.3。
  // 默认 false(沿用旧行为,产出 mp4);设为 true 后再选 transparent_format。
  transparent: boolean;
  transparent_format: TransparentFormat | null; // null = 跟随 transparent=false
}

export interface JobStatusResponse {
  id: string;
  status: JobStatus;
  progress: number; // 0-100
  output_url: string | null;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  // 后端 queue.get_job_status 透传 jobs.output_ext;老 job 可能是 null,
  // 前端默认按 'mp4' 处理,保证旧 config / 老数据不破坏 UI。
  output_ext: OutputExt | null;
  // 时间码 JSON 链接(见 docs/03-api.md §3.x 时间码导出):
  // 仅 done 且 timeline.json 存在时有值,前端据此显示「查看时间码」按钮。
  // TTS 任务没有 timeline.json → null。
  timeline_url: string | null;
  // 任务类型(2025-Q3 引入):'render'(视频) / 'tts'(语音合成)。
  // 前端按 kind 路由下载/播放 UI;老 job 默认 'render'。
  kind: 'render' | 'tts';
  // TTS 单段失败明细(见 docs/Qwen3-TTS_MultiSpeaker_Dialogue_Guide.md):
  // 仅 kind="tts" 的 done 任务里可能非空;render 任务与未跑完的任务里都是 null。
  // 失败不阻塞整体任务,该段回退静音。
  metadata_json: { failed_segments?: TtsFailedSegment[] } | null;
}

/** TTS 单段失败明细项 —— 与后端 tts_service.synthesize 写入的 failed_segments 一一对应。 */
export interface TtsFailedSegment {
  idx: number;
  speaker_id: string;
  speaker: string;
  text: string;
  reason: string;
}

/** Event payload pushed through the SSE stream. */
export interface RenderJobEvent {
  status: JobStatus;
  progress?: number;
  output_url?: string | null;
  error?: string | null;
  // SSE 增量事件里也可能带 output_ext(终态时);其余时刻从前一次的 snapshot 拿。
  output_ext?: OutputExt | null;
  // done 事件里也会带 timeline_url;前端无需再额外 GET 一次 job 状态就能展示按钮。
  timeline_url?: string | null;
  // 任务类型(2025-Q3);老 job 事件流里这个字段是 undefined,前端按 'render' 兜底。
  kind?: 'render' | 'tts';
  // TTS done 事件里带的失败明细(其它时刻为 undefined)。
  metadata_json?: { failed_segments?: TtsFailedSegment[] } | null;
}

/** GET /api/tts/by-source/{job_id} 响应(2025-Q3 引入)。 */
export interface TtsBySourceResponse {
  tts_job_id: string;
  status: JobStatus;
  progress: number;
  output_url: string | null;
  error: string | null;
  metadata_json: { failed_segments?: TtsFailedSegment[] } | null;
}

// ---------- 时间码 JSON(见 docs/03-api.md §3.x 时间码导出) ----------

/**
 * 时间码 JSON 里每条事件的类型标签。
 * - disclaimer: 片头 1s AI 声明卡
 * - intro: 开头特效(scanline / typewriter)
 * - msg: 普通消息(text / image / video / emoji)
 * - sys: 系统消息(幕间字幕)
 * - timestamp: 时间戳
 */
export type TimelineEventType = 'disclaimer' | 'intro' | 'msg' | 'sys' | 'timestamp';

/** 时间码 JSON 单条事件 —— 与后端 `build_timeline_with_durations()` 一一对应。 */
export interface TimelineEntry {
  id: string; // dom_id(disclaimer/intro 取固定值,消息取 'mN')
  at: number; // 出现时刻(毫秒,相对视频起点 0),与 build_timeline 对齐
  type: TimelineEventType;
  kind: string; // 渲染字段:disclaimer / intro / text / image / sys / timestamp / video / emoji
  sender_id: string;
  sender_name: string;
  summary: string; // 给表格用的简短摘要
  text: string | null;
  image_url: string | null;
  video_url: string | null;
  duration: string | null;
  appeared_at: number; // = at(冗余,方便前端过滤 / 排序)
  disappeared_at: number; // 消失时刻(毫秒);末条 = total_duration_ms
  duration_ms: number; // disappeared_at - appeared_at
}

/** 时间码 JSON 顶层结构,与后端 `recorder._write_timeline_json` 对齐。 */
export interface TimelineDocument {
  schema_version: '1.0';
  kind: 'chat';
  job_id: string;
  total_duration_ms: number;
  entries: TimelineEntry[];
}

// ---------- 多用户 / session 相关(新增) ----------

export type FileKind = 'avatar' | 'image' | 'background';

export interface FileInfo {
  id: string;
  session_id: string;
  user_id: string;
  kind: FileKind;
  ext: string;
  size: number;
  content_type: string | null;
  created_at: number;
  url: string; // /api/files/{id}
}

export interface JobSummary {
  id: string;
  session_id: string;
  user_id: string;
  status: JobStatus;
  progress: number;
  output_url: string | null;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  output_ext: OutputExt | null;
  timeline_url: string | null;
  // 任务类型(2025-Q3):'render'(视频) / 'tts'(语音合成);老 job 默认 'render'。
  kind?: 'render' | 'tts';
  // TTS 单段失败明细(与 JobStatusResponse.metadata_json 同语义)。
  metadata_json?: { failed_segments?: TtsFailedSegment[] } | null;
}

export interface SessionInfo {
  id: string;
  user_id: string;
  title: string | null;
  created_at: number;
  last_active_at: number;
  file_count: number;
  job_count: number;
}

export interface SessionDetail extends SessionInfo {
  files: FileInfo[];
  jobs: JobSummary[];
}

export interface ImportedFile {
  path_in_zip: string;
  file_id: string;
  url: string;
  kind: FileKind;
  size: number;
  deduped: boolean;
}

export interface ImportResponse {
  dsl: VideoDSL;
  uploaded_files: ImportedFile[];
  warnings: string[];
}

// ---------- AI 辅助生成 ----------

export interface AIQuotaStatus {
  daily_limit: number;
  used_today: number;
  remaining_today: number;
}

export interface GenerateDialogueRequest {
  session_id: string;
  synopsis: string;
  mode: Mode;
  style_theme: StyleTheme;
  intent: Intent;
  num_messages: number;
}

export interface ContinueDialogueRequest {
  session_id: string;
  dsl: VideoDSL;
  num_candidates: number;
}

export interface ContinueDialogueResponse {
  candidates: Message[];
}
