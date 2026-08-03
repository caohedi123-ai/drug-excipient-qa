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

// ── 流式问答请求管理（按会话隔离，支持多会话/多设备并行）──
// 用 Map<requestKey, AbortController> 替代单一全局 controller：
// 不同会话（不同 thread_id）的请求互不干扰；同一会话内新请求会中断旧请求（会话内串行语义）。
const controllers = new Map<string, AbortController>()

export function isRequestActive(requestKey?: string): boolean {
  return !!requestKey && controllers.has(requestKey)
}

export function abortActiveRequest(requestKey?: string): void {
  if (requestKey) {
    controllers.get(requestKey)?.abort()
    return
  }
  // 兼容旧的无参调用：中止所有进行中的请求。
  // 注意：不要 clear map——否则被中止的请求会因 isStale() 静默退出，
  // 上层收尾（onDone(undefined)/isStreaming 复位）将悬挂。保留 entry，
  // 让每个请求走 AbortError 路径自行 onDone 并在 finally 中清理自己。
  for (const c of controllers.values()) c.abort()
}

/**
 * 向真实后端发起 SSE 流式问答请求。
 * 后端：POST /api/chat { query, conversation_id, thread_id }
 * 推送：thinking / answer / error / [DONE]
 * @param requestKey 请求隔离键（前端传 thread_id）。同 key 的旧请求会被中断（会话内串行）；
 *   不同 key 的请求并行进行，互不干扰，终止后各回各自的会话。
 */
export async function sendChatMessage(
  query: string,
  threadId: string | null,
  callbacks: ChatCallbacks,
  requestKey?: string | null,
): Promise<void> {
  const key = requestKey || threadId || query

  // 同一会话的旧请求仍在进行 → 中断它（会话内串行；跨会话不干预）
  const prev = controllers.get(key)
  if (prev) prev.abort()

  const controller = new AbortController()
  controllers.set(key, controller)
  // 被同 key 新请求顶替后为 true：静默结束，不再触发任何回调（避免旧请求改写会话终态）
  const isStale = () => controllers.get(key) !== controller

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
    let hasError = false

    while (true) {
      if (isStale()) return  // 已被同会话新请求顶替：静默退出
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
          hasError = true
          callbacks.onError?.(evt.message || '处理出错')
          break  // 出错后终止本次流，避免继续触发回调
        }
      }
      if (hasError) break
    }

    if (!hasError) callbacks.onDone?.(finalAnswer || undefined)
  } catch (err: any) {
    if (isStale()) {
      // 被同会话新请求顶替：静默退出，不影响新请求
      return
    }
    if (err?.name === 'AbortError') {
      // 用户主动停止，正常结束（onDone(undefined)，由上层做收尾）
      callbacks.onDone?.(undefined)
    } else {
      callbacks.onError?.(err?.message || '请求失败，请检查后端服务是否运行')
    }
  } finally {
    // 仅当仍是本请求自己的 entry 时才清理，避免误删同 key 新请求
    if (controllers.get(key) === controller) {
      controllers.delete(key)
    }
  }
}
