/* 前端统一类型定义 */

export interface Citation {
  source_name: string
  source_url: string
  snippet: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  citations?: Citation[]
  thinking_steps?: string[]
  streaming?: boolean
  timestamp: string
}

export interface Conversation {
  id: string
  title: string
  thread_id: string
  created_at: string
  updated_at: string
}

export interface Reference {
  source: string
  title: string
  subtitle?: string
  score?: number
  url?: string
  sourceName?: string
  snippet?: string
}

// ── 速查历史 ──
export interface LookupHistoryItem {
  id: string
  name: string
  entity: Record<string, any> | null
  modules: Record<string, any>
  citations: Array<{ source_name: string; source_url: string; snippet: string }>
  created_at: string
}
