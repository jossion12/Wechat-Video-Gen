export type Mode = 'single' | 'group';
export type MessageKind = 'text' | 'image' | 'sys' | 'timestamp' | 'video' | 'emoji';
export type JobStatus = 'queued' | 'running' | 'done' | 'failed';
export type VideoKind = 'chat';
export type VideoTemplate = 'cyberpunk' | 'watercolor' | 'pixel' | 'comic' | 'noir' | 'ink';
export type StyleTheme = VideoTemplate;
export type Intent =
  | 'short_video_drama'
  | 'story_visualization'
  | 'teaching_simulation'
  | 'meme_sticker';
export type AIBadgeStyle = 'neon' | 'minimal' | 'retro';

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
};

/** 各主题首次启用时的推荐背景色。 */
export const THEME_DEFAULT_BACKGROUND: Record<StyleTheme, string> = {
  cyberpunk: '#0a0a12',
  watercolor: '#f7f4ed',
  pixel: '#051005',
  comic: '#ffffff',
  noir: '#f5f0e1',
  ink: '#f4ecd8',
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
  duration_ms: number | null; // null = auto
  opacity: number; // 0-1, default 1
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
}

export interface JobStatusResponse {
  id: string;
  status: JobStatus;
  progress: number; // 0-100
  output_url: string | null;
  error: string | null;
  created_at: number;
  finished_at: number | null;
}

/** Event payload pushed through the SSE stream. */
export interface RenderJobEvent {
  status: JobStatus;
  progress?: number;
  output_url?: string | null;
  error?: string | null;
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
