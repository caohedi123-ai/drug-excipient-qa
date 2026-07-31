// 通过 Vite 开发代理(/api → 后端)走同源请求，避免 CORS；
// 生产环境可经 Nginx 等同源反向代理，同样无需跨域。
const BASE_URL = ''

// ── Auth Token 管理 ──
const TOKEN_KEY = 'pharma_auth_token'
export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// 带 token 的通用 fetch
async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getStoredToken()
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return fetch(url, { ...options, headers })
}

// ── 原辅料速查（独立端点，不走 agent 规划）──
export interface LookupField {
  key: string
  label: string
  value: string
  source: string
  sourceUrl: string
  confidence: number
}

export interface LookupModule {
  fields: LookupField[]
  text_parts: string[]
  text_parts_cn: string[]
}

export interface ExcipientLookupCitation {
  source_name: string
  source_url: string
  snippet: string
}

export interface ExcipientLookupEntity {
  drug_name_cn?: string
  drug_name_en?: string
  excipient_name_cn?: string
  excipient_name_en?: string
  cas_number?: string
  product_type?: string
  unii_code?: string
  // 向后兼容
  query?: string
  canonical?: string
  cas?: string
}

export interface ExcipientLookupResult {
  ok: boolean
  content: string
  citations: ExcipientLookupCitation[]
  entity: ExcipientLookupEntity | null
  modules: Record<string, LookupModule>
}

export async function lookupExcipient(name: string): Promise<ExcipientLookupResult> {
  const res = await authFetch(`${BASE_URL}/api/excipient/lookup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) {
    if (res.status === 401) throw new Error('AUTH_REQUIRED')
    const text = await res.text().catch(() => '')
    throw new Error(text || `速查失败 (${res.status})`)
  }
  return res.json()
}

// ── 认证 ──
export interface LoginResult {
  ok: boolean
  token: string
  username: string
  message: string
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return res.json()
}

export async function checkAuth(): Promise<boolean> {
  try {
    const res = await authFetch(`${BASE_URL}/api/auth/me`)
    const data = await res.json()
    return data.ok === true
  } catch {
    return false
  }
}

// ── AI 问答会话历史 ──
export interface BackendConversation {
  id: string
  title: string
  thread_id: string
  created_at: string
  updated_at: string
}

export interface BackendConversationMessage {
  role: 'user' | 'assistant'
  content: string
  thinking_steps?: string[]
  references?: Array<{
    source_name: string
    source_url: string
    snippet: string
  }>
  timestamp: string
}

export async function fetchConversations(): Promise<BackendConversation[]> {
  const res = await authFetch(`${BASE_URL}/api/conversations`)
  if (!res.ok) throw new Error(`获取会话列表失败: ${res.status}`)
  return res.json()
}

export async function fetchConversationMessages(conversationId: string): Promise<BackendConversationMessage[]> {
  const res = await authFetch(`${BASE_URL}/api/conversations/${conversationId}/messages`)
  if (!res.ok) throw new Error(`获取消息失败: ${res.status}`)
  const data = await res.json()
  // 后端直接返回数组；若未来加了 messages 包裹层也兼容
  return Array.isArray(data) ? data : (data.messages || [])
}

// ── 速查历史 ──
export async function fetchLookupHistory(): Promise<any[]> {
  const res = await authFetch(`${BASE_URL}/api/lookup/history`)
  if (!res.ok) throw new Error('获取历史失败')
  return res.json()
}

export async function deleteLookupHistory(id: string): Promise<void> {
  const res = await authFetch(`${BASE_URL}/api/lookup/history/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('删除失败')
}

// 后端 SSE 事件类型（main.py 真实推送）
interface ThinkingEvent {
  type: 'thinking'
  steps: string[]
  description: string
}
interface AnswerEvent {
  type: 'answer'
  content: string
  citations: Array<{
    id: number
    source_name: string
    source_url: string
    snippet: string
    retrieval_query?: string
  }>
  conversation_id: string
  thread_id: string
}
interface ErrorEvent {
  type: 'error'
  message: string
}

export interface ThinkingStepData {
  steps: string[]
  current: string
}

export interface ChatCallbacks {
  onStep?: (data: ThinkingStepData) => void
  onSources?: (sources: Array<{ title: string; snippet: string; sourceUrl: string; sourceName: string }>) => void
  onToken?: (token: string) => void
  onDone?: (finalAnswer?: string) => void
  onError?: (errorMsg: string) => void
}

// 用 AbortController 支持「停止」；单请求串行，简化状态管理
let activeController: AbortController | null = null

export function isRequestActive(): boolean {
  return activeController !== null
}

export function abortActiveRequest(): void {
  if (activeController) {
    activeController.abort()
    activeController = null
  }
}

/**
 * 向真实后端发起 SSE 流式问答请求。
 * 后端：POST /api/chat { query, conversation_id, thread_id }
 * 推送：thinking / answer / error / [DONE]
 */
export async function sendChatMessage(
  query: string,
  threadId: string | null,
  callbacks: ChatCallbacks,
): Promise<void> {
  // 若上一次请求仍在进行，先中断（保证串行）
  if (activeController) {
    activeController.abort()
  }
  const controller = new AbortController()
  activeController = controller

  try {
    const res = await authFetch(`${BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        conversation_id: null,
        thread_id: threadId,
      }),
      signal: controller.signal,
    })

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new Error(`服务器错误 ${res.status}${text ? '：' + text : ''}`)
    }

    if (!res.body) {
      throw new Error('响应流不可用')
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalAnswer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE 以空行分隔事件
      const events = buffer.split('\n\n')
      buffer = events.pop() ?? ''

      for (const raw of events) {
        const line = raw.trim()
        if (!line.startsWith('data:')) continue
        let payload = line.slice(5).trim()
        if (payload === '[DONE]') continue

        let evt: ThinkingEvent | AnswerEvent | ErrorEvent
        try {
          evt = JSON.parse(payload)
        } catch {
          continue
        }

        if (evt.type === 'thinking') {
          const steps = Array.isArray(evt.steps) ? evt.steps : []
          const current = evt.description || ''
          callbacks.onStep?.({ steps, current })
        } else if (evt.type === 'answer') {
          // 后端按块增量推送，content 为增量片段，逐块累加
          const delta = evt.content || ''
          finalAnswer += delta
          if (evt.citations?.length) {
            callbacks.onSources?.(
              evt.citations.map(c => ({
                title: c.source_name,
                snippet: c.snippet || '',
                sourceUrl: c.source_url || '',
                sourceName: c.source_name,
              })),
            )
          }
          if (delta) callbacks.onToken?.(delta)
        } else if (evt.type === 'error') {
          callbacks.onError?.(evt.message || '处理出错')
        }
      }
    }

    callbacks.onDone?.(finalAnswer || undefined)
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      // 用户主动停止，正常结束
      callbacks.onDone?.(undefined)
    } else {
      callbacks.onError?.(err?.message || '请求失败，请检查后端服务是否运行')
    }
  } finally {
    if (activeController === controller) {
      activeController = null
    }
  }
}
