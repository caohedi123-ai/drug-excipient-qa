// 通过 Vite 开发代理(/api → 后端)走同源请求，避免 CORS；
// 生产环境可经 Nginx 等同源反向代理，同样无需跨域。
const BASE_URL = ''

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
    const res = await fetch(`${BASE_URL}/api/chat`, {
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
