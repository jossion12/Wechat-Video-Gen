export type Mode = 'single' | 'group';
export type MessageKind = 'text' | 'image' | 'sys' | 'timestamp' | 'video' | 'emoji';
export type JobStatus = 'queued' | 'running' | 'done' | 'failed';
export type VideoKind = 'chat';
export type VideoTemplate = 'wechat';

export interface StatusBar {
  time: string; // default '12:34'
  battery_level: number; // 0-100, default 100
  network_speed: string | null; // e.g. '3.5 K/s', '300 B/s'
  signal_type: string | null; // e.g. '5A', '5G', '4G'
  signal_type_secondary: string | null; // e.g. '5G', used when dual_sim is true
  dual_sim: boolean;
  show_wifi: boolean; // default true
  show_signal: boolean; // default true
  show_bluetooth: boolean;
  show_alarm: boolean;
  show_nfc: boolean;
  app_icons: string[]; // short names/initials for left-side app icons
}

export interface Participant {
  id: string; // unique within config, e.g. 'me', 'alice', 'bob'
  name: string; // display name, ≤16 chars
  avatar_url: string | null; // '/uploads/xxx.png' or null
  label: string | null; // subtitle in single chat / enterprise tag in group chat
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
}

/** 聊天场景配置。 */
export interface ChatScene {
  mode: Mode; // default 'group'
  title: string; // default '群聊'
  subtitle: string | null; // shown below title in single chat
  background: string; // default '#ededed'
  background_image_url: string | null; // '/uploads/xxx.png' or null; 有值时优先于 background
  duration_ms: number | null; // null = auto
  status_bar: StatusBar;
  member_count: number | null; // group member count, e.g. 221
  muted: boolean; // show mute bell in group header
  participants: Participant[]; // at least 2
  messages: Message[]; // at least 1, ≤30
}

/** 视频生成顶层 DSL。 */
export interface VideoDSL {
  schema_version: '1.0';
  kind: VideoKind;
  template: VideoTemplate;
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
