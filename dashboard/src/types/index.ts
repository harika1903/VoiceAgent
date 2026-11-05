// ── Agents ───────────────────────────────────────────────────────────────

export interface AgentSpec {
  name: string;
  system_prompt: string;
  greeting_instruction: string;
  language: string;
  voice: string | null;
  llm_model: string | null;
  speaker_lock: boolean;
  kb_file: string;
  kb_top_k: number;
}

export interface Agent extends AgentSpec {
  id: string;
  version: number;
}

// ── Calls ────────────────────────────────────────────────────────────────

export interface CallHistoryItem {
  id: string;
  agent_id: string;
  call_type: string;
  status: string;
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_secs: number | null;
  end_reason: string | null;
  summary: string | null;
}

export interface CallHistoryResponse {
  calls: CallHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TranscriptTurn {
  seq: number;
  role: string;
  text: string;
  at: string;
  interrupted: boolean;
}

export interface TranscriptResponse {
  session_id: string;
  agent_id: string;
  status: string;
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_secs: number | null;
  summary: string | null;
  turns: TranscriptTurn[];
}

export interface StartCallResponse {
  session_id: string;
  room: string;
  ws_token: string;
  worker_ws_url: string;
}

export interface SessionState {
  id: string;
  status: string;
  worker_ws_url: string | null;
}

// ── Knowledge Base ───────────────────────────────────────────────────────

export interface KBDocument {
  id: string;
  text: string;
  metadata: Record<string, unknown>;
}

export interface KBStats {
  size: number;
  sample: KBDocument[];
}

export interface KBSearchResponse {
  query: string;
  results: KBDocument[];
}

// ── Settings ─────────────────────────────────────────────────────────────

export interface ApiKeyItem {
  id: number;
  label: string;
  prefix: string;
  created_at: string;
  revoked_at: string | null;
}

export interface OrgProfile {
  id: string;
  name: string;
  max_concurrent_calls: number | null;
  created_at: string;
}

export interface UsageSummary {
  total_calls: number;
  total_duration_secs: number;
  avg_duration_secs: number;
  by_kind: { kind: string; total: number; count: number }[];
}
