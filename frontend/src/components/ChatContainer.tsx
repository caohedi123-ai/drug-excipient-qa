import { type FC, useState, useCallback, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ThinkingProcess } from './ThinkingProcess'
import { ReferenceList } from './ReferenceList'
import DataSourcePanel from './DataSourcePanel'
import { sendChatMessage, abortActiveRequest, isRequestActive, fetchConversationMessages } from '../lib/api'
import type { Conversation, Message } from '../types'

interface ChatContainerProps {
  conversation?: Conversation
  onUpdate: (conv: Conversation) => void
}

interface ThinkingStep {
  label: string
  status: 'pending' | 'active' | 'done' | 'error'
  detail?: string
}

interface RefItem {
  source: string
  sourceName: string
  title: string
  subtitle?: string
  score?: number
  url?: string
  snippet?: string
}

export const ChatContainer: FC<ChatContainerProps> = ({
  conversation,
  onUpdate,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([])
  const [references, setReferences] = useState<RefItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const lastConvIdRef = useRef<string | null>(null)
  const skipAutoScrollRef = useRef(false)

  // conversation ref —— 避免 handleSend 闭包过期
  const conversationRef = useRef(conversation)
  conversationRef.current = conversation

  // Refs to avoid stale closures when saving state
  const msgsRef = useRef(messages)
  const streamRef = useRef(streamingContent)
  const stepsRef = useRef(thinkingSteps)
  const refsRef = useRef(references)
  const errRef = useRef(error)
  const streamingRef = useRef(isStreaming)
  msgsRef.current = messages
  streamRef.current = streamingContent
  stepsRef.current = thinkingSteps
  refsRef.current = references
  errRef.current = error
  streamingRef.current = isStreaming

  // 跨会话状态持久化：切换对话时保存当前→恢复目标
  const savedStatesRef = useRef<Map<string, {
    messages: Message[]
    streamingContent: string
    thinkingSteps: ThinkingStep[]
    references: RefItem[]
    error: string | null
    isStreaming: boolean
  }>>(new Map())

  useEffect(() => {
    const newId = conversation?.id ?? null
    const oldId = lastConvIdRef.current
    if (oldId === newId) return  // 同一会话 prop 更新（如 thread_id 补齐），不重置

    // 保存当前会话状态
    if (oldId) {
      savedStatesRef.current.set(oldId, {
        messages: msgsRef.current,
        streamingContent: streamRef.current,
        thinkingSteps: stepsRef.current,
        references: refsRef.current,
        error: errRef.current,
        isStreaming: streamingRef.current,
      })
    }

    // 恢复/初始化目标会话状态
    if (newId) {
      const saved = savedStatesRef.current.get(newId)
      if (saved) {
        // 已缓存在内存中（本次会话中切换过的），直接恢复
        setMessages(saved.messages)
        setStreamingContent(saved.streamingContent)
        setThinkingSteps(saved.thinkingSteps)
        setReferences(saved.references)
        setError(saved.error)
        setIsStreaming(saved.isStreaming)
      } else {
        // 未缓存 —— 从后端加载历史消息
        setMessages([])
        setStreamingContent('')
        setThinkingSteps([])
        setReferences([])
        setError(null)
        setIsStreaming(false)
        setLoadingHistory(true)
        fetchConversationMessages(newId)
          .then(backendMsgs => {
            if (backendMsgs && backendMsgs.length > 0) {
              const loaded: Message[] = backendMsgs.map((m: any) => ({
                id: m.id || crypto.randomUUID(),
                role: m.role as 'user' | 'assistant',
                content: m.content || '',
                timestamp: m.timestamp || m.created_at || new Date().toISOString(),
              }))
              skipAutoScrollRef.current = true  // 加载历史不自动滚到底部
              setMessages(loaded)
              // 缓存到 savedStatesRef，避免重复加载
              savedStatesRef.current.set(newId, {
                messages: loaded,
                streamingContent: '',
                thinkingSteps: [],
                references: [],
                error: null,
                isStreaming: false,
              })
            }
          })
          .catch(err => console.warn('加载会话消息失败:', err))
          .finally(() => setLoadingHistory(false))
      }
    }

    lastConvIdRef.current = newId
  }, [conversation?.id])

  useEffect(() => {
    // 跳过历史加载时的自动滚动，仅流式输出时自动滚到底部
    if (skipAutoScrollRef.current) {
      skipAutoScrollRef.current = false
      return
    }
    try { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) } catch {}
  }, [streamingContent, messages.length, thinkingSteps.length, references.length])

  const handleSend = useCallback((question: string) => {
    if (!question.trim()) return

    // reset states
    setStreamingContent('')
    setThinkingSteps([])
    setReferences([])
    setError(null)

    const ts = new Date().toISOString()

    // add user message with id
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
      timestamp: ts,
    }
    setMessages(prev => [...prev, userMsg])

    // 确保有稳定的 thread_id，保证后端会话连续性（修复 thread_id 缺失导致每次新建会话）
    const conv = conversationRef.current
    let threadId = conv?.thread_id ?? null
    if (!conv || !conv.thread_id) {
      const newThreadId = crypto.randomUUID()
      threadId = newThreadId
      const newConv: Conversation = conv
        ? { ...conv, thread_id: newThreadId }
        : {
            id: crypto.randomUUID(),
            title: question.slice(0, 30),
            thread_id: newThreadId,
            created_at: ts,
            updated_at: ts,
          }
      onUpdate(newConv)
    }
    setIsStreaming(true)

    sendChatMessage(question, threadId, {
      onStep: ({ steps }) => {
        // 后端每次推送完整的 thinking_steps 累积列表；最后一条为「当前正在思考」
        setThinkingSteps(
          steps.map((s, i) => ({
            label: s,
            status: (i < steps.length - 1 ? 'done' : 'active') as ThinkingStep['status'],
          })),
        )
      },
      onSources: (sources) => {
        setReferences(prev => {
          // 去重：同一 sourceUrl 只保留一次
          const seen = new Set(prev.map(r => r.url))
          const newItems: RefItem[] = []
          for (const s of sources) {
            const name = s.sourceName || s.title || ''
            const url = s.sourceUrl || ''
            if (url && seen.has(url)) continue
            if (url) seen.add(url)
            let source = 'web'
            if (/iig/i.test(name)) source = 'fda_iig'
            else if (/unii/i.test(name)) source = 'fda_unii'
            else if (/pubchem/i.test(name)) source = 'pubchem'
            else if (/drugbank/i.test(name)) source = 'drugbank'
            else if (/dailymed/i.test(name)) source = 'dailymed'
            else if (/wikipedia/i.test(name)) source = 'wikipedia'
            else if (/pubmed/i.test(name)) source = 'pubmed'
            newItems.push({
              source,
              sourceName: name,
              title: s.title || name,
              subtitle: s.snippet ? s.snippet.slice(0, 160) : undefined,
              snippet: s.snippet || '',
              url,
            })
          }
          return [...prev, ...newItems]
        })
      },
      onToken: (token) => {
        setStreamingContent(prev => prev + token)
      },
      onDone: (finalAnswer) => {
        if (finalAnswer) {
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: finalAnswer,
            timestamp: new Date().toISOString(),
          }
          setMessages(prev => [...prev, assistantMsg])
        }
        setStreamingContent('')
        // 保留思考过程与参考来源，便于用户回看「问题拆解情况」
        setThinkingSteps(prev => prev.map(s => ({ ...s, status: 'done' as const })))
        setIsStreaming(false)
      },
      onError: (errMsg) => {
        setError(errMsg)
        setThinkingSteps(prev =>
          prev.map(s => s.status === 'active' ? { ...s, status: 'error' as const } : s)
        )
        setIsStreaming(false)
      },
    })
  }, [onUpdate])   // conversation 通过 conversationRef 读取，不依赖 props

  const handleStop = useCallback(() => {
    abortActiveRequest()
    if (streamingContent) {
      const partialMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: streamingContent + '\n\n*[已中断]*',
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, partialMsg])
    }
    setStreamingContent('')
    setThinkingSteps([])
    setReferences([])
    setError(null)
    setIsStreaming(false)
  }, [streamingContent])

  const hasStream = streamingContent.length > 0

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
      {/* 数据源清单（常态化显示，有消息时默认折叠） */}
      <div className="max-w-3xl mx-auto mb-3">
        <DataSourcePanel defaultExpanded={messages.length === 0 && !hasStream && !error} />
      </div>

        {loadingHistory && (
          <div className="flex items-center justify-center py-10">
            <div className="text-center">
              <svg className="w-5 h-5 mx-auto mb-2 text-[#58a6ff] animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <p className="text-xs text-[#8b949e]">加载历史消息中...</p>
            </div>
          </div>
        )}

        {!loadingHistory && messages.length === 0 && !hasStream && !error && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-md">
              <div className="w-12 h-12 mx-auto mb-4 rounded-lg bg-[#1f6feb1a] border border-[#58a6ff33] flex items-center justify-center">
                <svg className="w-6 h-6 text-[#58a6ff]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
              </div>
              <h2 className="text-base font-semibold text-[#e6edf3] mb-1">中诺药物原辅料知识问答</h2>
              <p className="text-xs text-[#8b949e]">
                输入药物名称或原辅料相关问题，AI 将检索 FDA IIG、UNII 等数据库并给出专业回答
              </p>
            </div>
          </div>
        )}

        <div className="max-w-3xl mx-auto space-y-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

          {/* 等待首个事件时的「正在分析」占位，避免用户傻等 */}
          {isStreaming && !hasStream && thinkingSteps.length === 0 && references.length === 0 && (
            <div className="bubble-assistant flex items-center gap-2 text-[#8b949e]">
              <span className="inline-block w-2 h-2 rounded-full bg-[#58a6ff] animate-pulse" />
              AI 正在分析你的问题，请稍候…
            </div>
          )}

          {/* 思考过程 / 问题拆解（流式增长，完成后保留，可折叠） */}
          {thinkingSteps.length > 0 && (
            <details className="thinking-details group" open>
              <summary className="text-xs font-medium text-[#8b949e] flex items-center gap-1.5 cursor-pointer hover:text-[#e6edf3] select-none py-0.5">
                <svg className="w-3 h-3 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                思考过程
              </summary>
              <div className="mt-1">
                <ThinkingProcess steps={thinkingSteps} />
              </div>
            </details>
          )}

          {/* 流式回答 */}
          {hasStream && (
            <div className="bubble-assistant">
              <div className="text-xs font-medium text-[#8b949e] mb-1 flex items-center gap-1.5">
                <svg className="w-3 h-3 text-[#58a6ff]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
                AI 回答
              </div>
              <div className="text-sm break-words text-[#e6edf3] markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
                <span className="inline-block w-2 h-4 ml-0.5 bg-[#58a6ff] animate-pulse align-text-bottom" />
              </div>
            </div>
          )}

          {/* 参考来源（可折叠） */}
          {references.length > 0 && (
            <details className="reference-details group">
              <summary className="text-xs font-medium text-[#8b949e] flex items-center gap-1.5 cursor-pointer hover:text-[#e6edf3] select-none py-0.5">
                <svg className="w-3 h-3 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                参考来源 ({references.length})
              </summary>
              <div className="mt-1">
                <ReferenceList references={references} />
              </div>
            </details>
          )}

          {error && (
            <div className="bg-[#f851491a] border border-[#f8514933] rounded-md px-3 py-2 text-sm text-[#f85149]">
              {error}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-[#21262d] px-4 py-3 bg-[#0d1117]">
        <div className="max-w-3xl mx-auto">
          <ChatInput
            onSend={handleSend}
            disabled={isStreaming}
          />
        </div>
      </div>
    </div>
  )
}
