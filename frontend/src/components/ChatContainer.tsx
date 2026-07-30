import { type FC, useState, useCallback, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ThinkingProcess } from './ThinkingProcess'
import { ReferenceList } from './ReferenceList'
import { sendChatMessage, abortActiveRequest, isRequestActive } from '../lib/api'
import type { Conversation, Message } from '../types'

interface ChatContainerProps {
  conversation?: Conversation
  onUpdate: (conv: Conversation) => void
  onToggleSidebar: () => void
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
  onToggleSidebar,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([])
  const [references, setReferences] = useState<RefItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // reset messages when conversation changes
  useEffect(() => {
    setMessages([])
    setStreamingContent('')
    setThinkingSteps([])
    setReferences([])
    setError(null)
  }, [conversation?.id])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
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
    let threadId = conversation?.thread_id ?? null
    if (!conversation || !conversation.thread_id) {
      const newThreadId = crypto.randomUUID()
      threadId = newThreadId
      const conv: Conversation = conversation
        ? { ...conversation, thread_id: newThreadId }
        : {
            id: crypto.randomUUID(),
            title: question.slice(0, 30),
            thread_id: newThreadId,
            created_at: ts,
            updated_at: ts,
          }
      onUpdate(conv)
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
  }, [conversation, onUpdate])

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
    <div className="flex-1 flex flex-col h-full min-w-0">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 h-10 border-b border-[#21262d] bg-[#0d1117]">
        <button
          onClick={onToggleSidebar}
          className="p-1 rounded-md text-[#8b949e] hover:text-[#e6edf3] hover:bg-[#1c2128] transition-colors duration-100"
          title="切换侧边栏"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <div className="flex-1 flex items-center gap-2 min-w-0">
          <svg className="w-4 h-4 text-[#58a6ff] flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
          </svg>
          <span className="text-sm font-medium text-[#e6edf3] truncate">
            中诺药物原辅料知识问答
          </span>
          <span className="text-[10px] text-[#484f58] uppercase tracking-wider border border-[#21262d] rounded px-1.5">Beta</span>
        </div>
        {isStreaming && (
          <button onClick={handleStop} className="btn-danger">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor"/>
            </svg>
            停止
          </button>
        )}
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !hasStream && !error && (
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
