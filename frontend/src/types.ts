export type Mode = 'single' | 'group';
export type MessageKind = 'text' | 'image' | 'sys';
export type JobStatus = 'queued' | 'running' | 'done' | 'failed';

export interface Participant {
  id: string; // unique within config, e.g. 'me', 'alice', 'bob'
  name: string; // display name, ≤16 chars
  avatar_url: string | null; // '/uploads/xxx.png' or null
}

export interface Message {
  sender_id: string; // references Participant.id; '__system__' for sys
  kind: MessageKind;
  text: string | null;
  image_url: string | null;
  delay_ms: number; // default 1500
}

export interface ChatConfig {
  mode: Mode; // default 'group'
  title: string; // default '群聊'
  background: string; // default '#ededed'
  duration_ms: number | null; // null = auto
  participants: Participant[]; // at least 2
  messages: Message[]; // at least 1, ≤30
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
